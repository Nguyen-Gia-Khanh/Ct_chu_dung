/* Small Windows launcher. The Python UI, features, and data stay on disk. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define PATH_CAPACITY 4096
#define OUTPUT_CAPACITY 3500

static void show_error(const wchar_t *message) {
    MessageBoxW(NULL, message, L"Warehouse launcher", MB_OK | MB_ICONERROR);
}

static int path_exists(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void keep_output(char *output, size_t *length, const char *chunk, size_t count) {
    size_t discarded = *length + count > OUTPUT_CAPACITY
        ? *length + count - OUTPUT_CAPACITY : 0;
    if (discarded) {
        memmove(output, output + discarded, *length - discarded);
        *length -= discarded;
    }
    memcpy(output + *length, chunk, count);
    *length += count;
    output[*length] = '\0';
}

static void collect_available(HANDLE pipe, char *output, size_t *length) {
    DWORD available;
    char chunk[1024];
    while (PeekNamedPipe(pipe, NULL, 0, NULL, &available, NULL) && available) {
        DWORD read_count = 0;
        DWORD requested = available < sizeof(chunk) ? available : sizeof(chunk);
        if (!ReadFile(pipe, chunk, requested, &read_count, NULL) || !read_count) {
            break;
        }
        keep_output(output, length, chunk, read_count);
    }
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance;
    (void)previous;
    (void)show;

    wchar_t executable[PATH_CAPACITY];
    DWORD length = GetModuleFileNameW(NULL, executable, PATH_CAPACITY);
    if (!length || length >= PATH_CAPACITY) {
        show_error(L"Could not find the launcher folder.");
        return 1;
    }
    wchar_t *basename = wcsrchr(executable, L'\\');
    if (!basename) {
        show_error(L"Could not read the launcher name.");
        return 1;
    }
    const wchar_t *script_name;
    if (_wcsicmp(basename + 1, L"warehouse_mapper.exe") == 0) {
        script_name = L"warehouse_mapper.py";
    } else if (_wcsicmp(basename + 1, L"warehouse_label_printer.exe") == 0) {
        script_name = L"warehouse_label_printer.py";
    } else {
        show_error(L"This launcher must be named warehouse_mapper.exe or warehouse_label_printer.exe.");
        return 1;
    }
    *basename = L'\0';
    const wchar_t *root = executable;

    wchar_t script[PATH_CAPACITY];
    wchar_t venv_relative[PATH_CAPACITY];
    wchar_t python[PATH_CAPACITY];
    DWORD python_length;
    if (swprintf(script, PATH_CAPACITY, L"%ls\\%ls", root, script_name) < 0 ||
        swprintf(venv_relative, PATH_CAPACITY,
                 L"%ls\\.venv\\Scripts\\python.exe", root) < 0) {
        show_error(L"The script or Python path is too long.");
        return 1;
    }
    python_length = GetFullPathNameW(venv_relative, PATH_CAPACITY, python, NULL);
    if (!python_length || python_length >= PATH_CAPACITY) {
        show_error(L"The script or Python path is too long.");
        return 1;
    }
    if (!path_exists(script)) {
        show_error(L"The Python script is missing beside this launcher.");
        return 1;
    }
    if (!path_exists(python)) {
        wchar_t message[PATH_CAPACITY + 128];
        swprintf(message, sizeof(message) / sizeof(message[0]),
                 L"The project venv was not found:\n\n%ls\n\nRun setup_venv.cmd in the launcher folder.", python);
        show_error(message);
        return 1;
    }

    if (!arguments) arguments = L"";
    size_t command_length = wcslen(python) + wcslen(script) + wcslen(arguments) + 8;
    wchar_t *command = calloc(command_length, sizeof(wchar_t));
    if (!command) {
        show_error(L"Could not allocate the launch command.");
        return 1;
    }
    swprintf(command, command_length, L"\"%ls\" \"%ls\" %ls", python, script, arguments);

    SECURITY_ATTRIBUTES security = {sizeof(security), NULL, TRUE};
    HANDLE read_pipe = NULL;
    HANDLE write_pipe = NULL;
    HANDLE null_input = CreateFileW(L"NUL", GENERIC_READ,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                                    &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (null_input == INVALID_HANDLE_VALUE ||
        !CreatePipe(&read_pipe, &write_pipe, &security, 0) ||
        !SetHandleInformation(read_pipe, HANDLE_FLAG_INHERIT, 0)) {
        show_error(L"Could not prepare Python error reporting.");
        if (null_input != INVALID_HANDLE_VALUE) CloseHandle(null_input);
        if (read_pipe) CloseHandle(read_pipe);
        if (write_pipe) CloseHandle(write_pipe);
        free(command);
        return 1;
    }

    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = null_input;
    startup.hStdOutput = write_pipe;
    startup.hStdError = write_pipe;
    PROCESS_INFORMATION process = {0};
    BOOL started = CreateProcessW(python, command, NULL, NULL, TRUE,
                                  CREATE_NO_WINDOW, NULL, root, &startup, &process);
    DWORD start_error = started ? 0 : GetLastError();
    free(command);
    CloseHandle(null_input);
    CloseHandle(write_pipe);
    if (!started) {
        wchar_t message[PATH_CAPACITY + 128];
        swprintf(message, sizeof(message) / sizeof(message[0]),
                 L"Could not start the project Python:\n\n%ls\n\nWindows error %lu", python, start_error);
        show_error(message);
        CloseHandle(read_pipe);
        return 1;
    }

    char output[OUTPUT_CAPACITY + 1] = {0};
    size_t output_length = 0;
    while (WaitForSingleObject(process.hProcess, 100) == WAIT_TIMEOUT) {
        collect_available(read_pipe, output, &output_length);
    }
    collect_available(read_pipe, output, &output_length);
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(read_pipe);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);

    if (exit_code != 0) {
        wchar_t details[OUTPUT_CAPACITY + 1] = {0};
        if (output_length &&
            !MultiByteToWideChar(CP_UTF8, 0, output, -1, details, OUTPUT_CAPACITY + 1)) {
            MultiByteToWideChar(CP_ACP, 0, output, -1, details, OUTPUT_CAPACITY + 1);
        }
        wchar_t message[OUTPUT_CAPACITY + 256];
        swprintf(message, sizeof(message) / sizeof(message[0]),
                 L"The Python app exited with code %lu.\n\n%ls", exit_code,
                 details[0] ? details : L"Run the .py launcher in a terminal to see the error.");
        show_error(message);
    }
    return (int)exit_code;
}
