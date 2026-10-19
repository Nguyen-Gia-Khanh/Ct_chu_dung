//! Thin shell: starts the Python sidecar (`python -m mapper.rpc`) and forwards calls.
//!
//! The front end calls one command, `rpc(method, params)`. Each call becomes a JSON
//! line on the sidecar's stdin; replies come back on stdout matched by id. Lines
//! without an id are events, re-emitted to the window as `sidecar://<name>`.

use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tokio::sync::oneshot;

type Pending = Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>>;

struct Sidecar {
    child: Child,
    stdin: ChildStdin,
}

struct Bridge {
    root: PathBuf,
    database: Option<String>,
    sidecar: Mutex<Option<Sidecar>>,
    pending: Pending,
    next_id: AtomicU64,
}

fn error(kind: &str, message: impl Into<String>) -> Value {
    json!({ "type": kind, "message": message.into() })
}

/// The repository folder: `WAREHOUSE_REPO`, or the nearest folder above the exe
/// that contains the Python package (works for the copied exe and for dev builds).
fn repository_root() -> Result<PathBuf, String> {
    if let Ok(dir) = std::env::var("WAREHOUSE_REPO") {
        return Ok(PathBuf::from(dir));
    }
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    exe.ancestors()
        .find(|dir| dir.join("mapper").join("rpc").join("__main__.py").is_file())
        .map(Path::to_path_buf)
        .ok_or_else(|| "Put the app inside the warehouse project folder (mapper/ was not found).".into())
}

/// `--db PATH` on the app's command line, else `WAREHOUSE_DB`.
fn database_argument() -> Option<String> {
    let args: Vec<String> = std::env::args().collect();
    args.iter()
        .position(|arg| arg == "--db")
        .and_then(|index| args.get(index + 1).cloned())
        .or_else(|| std::env::var("WAREHOUSE_DB").ok())
}

impl Bridge {
    fn spawn(&self, app: &AppHandle) -> Result<Sidecar, Value> {
        let venv_python = self.root.join(".venv").join("Scripts").join("python.exe");
        let python = if venv_python.is_file() { venv_python } else { PathBuf::from("python") };
        let logs = self.root.join("data").join("logs");
        let _ = fs::create_dir_all(&logs);
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("desktop-sidecar.log"))
            .map_err(|e| error("SidecarFailed", e.to_string()))?;

        let mut command = Command::new(python);
        command
            .args(["-X", "utf8", "-m", "mapper.rpc"])
            .current_dir(&self.root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(log);
        if let Some(database) = &self.database {
            command.args(["--db", database]);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = command
            .spawn()
            .map_err(|e| error("SidecarFailed", format!("Could not start Python: {e}")))?;
        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");

        let pending = self.pending.clone();
        let app = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                let Ok(message) = serde_json::from_str::<Value>(&line) else { continue };
                if let Some(event) = message.get("event").and_then(Value::as_str) {
                    let data = message.get("data").cloned().unwrap_or(Value::Null);
                    let _ = app.emit(&format!("sidecar://{event}"), data);
                } else if let Some(id) = message.get("id").and_then(Value::as_u64) {
                    if let Some(reply) = pending.lock().unwrap().remove(&id) {
                        let _ = reply.send(message);
                    }
                }
            }
            for (_, reply) in pending.lock().unwrap().drain() {
                let _ = reply.send(json!({ "error": error("SidecarStopped", "The data service stopped. Try again.") }));
            }
            let _ = app.emit("sidecar://exit", ());
        });
        Ok(Sidecar { child, stdin })
    }

    /// Write one request, starting (or restarting) the sidecar when needed.
    fn send(&self, app: &AppHandle, line: &str) -> Result<(), Value> {
        let mut guard = self.sidecar.lock().unwrap();
        let alive = matches!(guard.as_mut().map(|s| s.child.try_wait()), Some(Ok(None)));
        if !alive {
            *guard = Some(self.spawn(app)?);
        }
        let sidecar = guard.as_mut().expect("started above");
        if let Err(e) = sidecar.stdin.write_all(line.as_bytes()).and_then(|_| sidecar.stdin.flush()) {
            *guard = None;
            return Err(error("SidecarStopped", e.to_string()));
        }
        Ok(())
    }

    fn stop(&self) {
        if let Some(mut sidecar) = self.sidecar.lock().unwrap().take() {
            let _ = sidecar.stdin.write_all(b"{\"id\":0,\"method\":\"shutdown\"}\n");
            let _ = sidecar.stdin.flush();
            for _ in 0..30 {
                if matches!(sidecar.child.try_wait(), Ok(Some(_))) {
                    return;
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            let _ = sidecar.child.kill();
        }
    }
}

#[tauri::command]
async fn rpc(app: AppHandle, bridge: State<'_, Bridge>, method: String, params: Option<Value>) -> Result<Value, Value> {
    let id = bridge.next_id.fetch_add(1, Ordering::Relaxed);
    let (sender, receiver) = oneshot::channel();
    bridge.pending.lock().unwrap().insert(id, sender);
    let line = json!({ "id": id, "method": method, "params": params.unwrap_or_else(|| json!({})) }).to_string() + "\n";
    if let Err(problem) = bridge.send(&app, &line) {
        bridge.pending.lock().unwrap().remove(&id);
        return Err(problem);
    }
    let reply = receiver
        .await
        .map_err(|_| error("SidecarStopped", "The data service stopped. Try again."))?;
    match reply.get("error") {
        Some(problem) => Err(problem.clone()),
        None => Ok(reply.get("result").cloned().unwrap_or(Value::Null)),
    }
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let root = repository_root().map_err(|message| -> Box<dyn std::error::Error> { message.into() })?;
            app.manage(Bridge {
                root,
                database: database_argument(),
                sidecar: Mutex::new(None),
                pending: Arc::new(Mutex::new(HashMap::new())),
                next_id: AtomicU64::new(1),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![rpc])
        .build(tauri::generate_context!())
        .expect("error while building the app");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Bridge>().stop();
        }
    });
}
