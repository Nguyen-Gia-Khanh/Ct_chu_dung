import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
import threading
from pathlib import Path

class ERPApp:

    def __init__(self, button_commands):

        # ======================================================
        # Main Window
        # ======================================================

        self.button_commands = button_commands

        self.root = tk.Tk()

        self.root.title("Simple ERP")

        # Start maximized
        self.root.state("zoomed")

        # Default size if maximized isn't supported
        self.root.geometry("600x1200")

        # Default mode is "analysis"
        self.mode = tk.StringVar(value="analysis")

        # ======================================================
        # Build UI
        # ======================================================

        self.create_menu()

        self.create_toolbar()

        self.create_main_area()

        self.create_statusbar()

    # ==========================================================
    # Menu Bar
    # ==========================================================

    def create_menu(self):

        menubar = tk.Menu(self.root)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)

        file_menu.add_command(
            label="Import to Database",
            command=self.import_database
        )

        file_menu.add_command(
            label="Construct XLSX",
            command=self.construct_xlsx
        )

        file_menu.add_separator()

        file_menu.add_command(
            label="Exit",
            command=self.root.destroy
        )

        menubar.add_cascade(
            label="File",
            menu=file_menu
        )

        # Charts menu
        chart_menu = tk.Menu(menubar, tearoff=0)

        chart_menu.add_command(
            label="Update Charts",
            command=self.update_charts
        )

        menubar.add_cascade(
            label="Charts",
            menu=chart_menu
        )

        # Mode menu
        mode_menu = tk.Menu(
            menubar,
            tearoff=0
        )

        mode_menu.add_radiobutton(
            label="Analysis",
            variable=self.mode,
            value="analysis",
            command=self.mode_changed
        )

        mode_menu.add_radiobutton(
            label="JSON Import",
            variable=self.mode,
            value="json",
            command=self.mode_changed
        )

        mode_menu.add_radiobutton(
            label="SQLite (Coming Soon)",
            variable=self.mode,
            value="sqlite",
            state="disabled",          # Remove this when implemented
            command=self.mode_changed
        )

        menubar.add_cascade(
            label="Mode Switch",
            menu=mode_menu
        )

        #=== Add more menus above here if needed ===#
        self.root.config(menu=menubar)

    # ==========================================================
    # Exclusive Features
    # ==========================================================

    # Log
    def log(self, message):

        self.console.insert(tk.END, message + "\n")

        self.console.see(tk.END)

    # Threading
    def run_background(self, func):
        threading.Thread(
            target=func,
            args=(self,),
            daemon=True
        ).start()

    # Tree update
    def update_directory_tree(self, root_path: Path):

        # Clear the old tree
        self.tree.delete(*self.tree.get_children())

        # Root node (full path)
        root_node = self.tree.insert(
            "",
            tk.END,
            text=str(root_path),
            open=True
        )

        # Populate children
        self.populate_tree(root_node, root_path)

    def populate_tree(self, parent, folder: Path):

        try:

            # Folders first
            folders = sorted(
                [p for p in folder.iterdir() if p.is_dir()],
                key=lambda p: p.name.lower()
            )

            # Files second
            files = sorted(
                [p for p in folder.iterdir() if p.is_file()],
                key=lambda p: p.name.lower()
            )

            # Insert folders
            for subfolder in folders:

                node = self.tree.insert(
                    parent,
                    "end",
                    text=subfolder.name,
                    open=False
                )

                # Recurse
                self.populate_tree(node, subfolder)

            # Insert files
            for file in files:

                self.tree.insert(
                    parent,
                    "end",
                    text=file.name
                )

        except PermissionError:
            pass

    def tree_mousewheel(self, event):

        # if event.state & 0x0001:        # Shift key is currently held

        #     self.tree.xview_scroll(
        #         -1 if event.delta > 0 else 1,
        #         "units"
        #     )

        # else:

            self.tree.yview_scroll(
                -1 if event.delta > 0 else 1,
                "units"
            )

    def mode_changed(self):

        mode = self.mode.get()

        self.log(f"Current mode: {mode}")

    # ==========================================================
    # Toolbar
    # ==========================================================

    def create_toolbar(self):

        toolbar = ttk.Frame(self.root)

        toolbar.pack(fill="x")

        ttk.Button(
            toolbar,
            text="Select Directory",
            command=self.select_directory
        ).pack(side="left", padx=5, pady=5)

        ttk.Button(
            toolbar,
            text="Import",
            command=self.import_database
        ).pack(side="left", padx=5, pady=5)

        ttk.Button(
            toolbar,
            text="Construct XLSX",
            command=self.construct_xlsx
        ).pack(side="left", padx=5)

        ttk.Button(
            toolbar,
            text="Update Charts",
            command=self.update_charts
        ).pack(side="left", padx=5)

    # ==========================================================
    # Main Layout
    # ==========================================================

    def create_main_area(self):

        # Horizontal split
        main = ttk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL
        )

        main.pack(
            fill="both",
            expand=True
        )

        # ------------------------------------------------------
        # LEFT : Inventory Tree
        # ------------------------------------------------------

        left_frame = ttk.Frame(main)

        # Frame to hold TreeView + Scrollbars
        tree_frame = ttk.Frame(left_frame)

        tree_frame.pack(
            fill="both",
            expand=True,
            padx=5,
            pady=5
        )

        # TreeView
        self.tree = ttk.Treeview(tree_frame)
        self.tree.bind("<MouseWheel>", self.tree_mousewheel)
        self.tree.column("#0", stretch=True)

        # Vertical scrollbar
        v_scroll = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self.tree.yview
        )

        # Horizontal scrollbar
        h_scroll = ttk.Scrollbar(
            tree_frame,
            orient="horizontal",
            command=self.tree.xview
        )

        # Connect TreeView to scrollbars
        self.tree.configure(
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set
        )

        # Layout
        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        main.add(left_frame, weight=1)

        # ------------------------------------------------------
        # RIGHT : Dashboard + Console
        # ------------------------------------------------------

        right = ttk.PanedWindow(
            main,
            orient=tk.VERTICAL
        )

        main.add(right, weight=4)

        # Dashboard

        dashboard = ttk.LabelFrame(
            right,
            text="Dashboard"
        )

        right.add(dashboard, weight=3)

        ttk.Label(
            dashboard,
            text="Matplotlib chart goes here"
        ).pack(expand=True)

        # Console

        console_frame = ttk.LabelFrame(
            right,
            text="Console"
        )

        right.add(console_frame, weight=1)

        self.console = ScrolledText(
            console_frame,
            height=10
        )

        self.console.pack(
            fill="both",
            expand=True
        )

        self.console.insert(
            tk.END,
            "Application started...\n"
        )

    # ==========================================================
    # Status Bar
    # ==========================================================

    def create_statusbar(self):

        self.status = ttk.Label(
            self.root,
            text="Ready",
            anchor="w"
        )

        self.status.pack(
            fill="x",
            side="bottom"
        )

    # ==========================================================
    # Button Functions
    # ==========================================================

    def import_database(self):
        self.run_background(self.button_commands["import"])


    def construct_xlsx(self):
        self.run_background(self.button_commands["build"])


    def update_charts(self):
        self.run_background(self.button_commands["charts"])

    def select_directory(self):
        self.run_background(self.button_commands["directory"])

    # ==========================================================
    # Run
    # ==========================================================

    def run(self):

        self.root.mainloop()


# ==============================================================
# Program Entry
# ==============================================================

if __name__ == "__main__":

    from debug_material import BUTTON_COMMANDS

    app = ERPApp(BUTTON_COMMANDS)

    app.run()