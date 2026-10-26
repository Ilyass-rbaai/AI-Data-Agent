"""AI Data Agent desktop workspace. Run: uv run python main.py"""
import argparse
import json
import os
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Use physical screen coordinates on Windows to avoid oversized or clipped windows.
if os.name == "nt":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parent


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    return str(content)


def run_request(question, mode="Auto"):
    # Lazy imports let the interface open even before credentials are configured.
    from dotenv import load_dotenv
    from langchain_core.messages import HumanMessage
    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Add OPENAI_API_KEY to your project .env file, then try again.")
    if mode == "SQL":
        from agents.sql_analyst import sql_analyst
        result = sql_analyst.invoke({
            "messages": [], "user_question": question,
            "curated_question": "", "prompt_query_context": "",
            "generated_sql_query": "", "is_safe": None, "comment": "",
            "sql_query_execution_result": "", "final_answer": "",
        })
        return {"answer": content_text(result["final_answer"]), "route": "SQL",
                "sql": result.get("generated_sql_query", ""),
                "review": result.get("comment", ""), "safe": result.get("is_safe")}
    if mode == "ETL":
        from agents.etl_analyst import etl_analyst
        result = etl_analyst.invoke({"messages": [HumanMessage(content=question)]})
        return {"answer": content_text(result["messages"][-1].content), "route": "ETL"}
    from agents.data_agent import data_agent
    result = data_agent.invoke({"messages": [HumanMessage(content=question)],
                                "route_response": ""})
    return {"answer": content_text(result["messages"][-1].content),
            "route": result.get("route_response", "auto").upper()}


class Workspace:
    def __init__(self, root, runner=run_request):
        self.root, self.runner = root, runner
        self.events = queue.Queue()
        self.history = []
        self.busy = False
        self.started = 0
        root.title("AI Data Agent — Studio")
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width, height = min(1320, screen_w - 80), min(940, screen_h - 100)
        root.geometry(f"{width}x{height}")
        root.minsize(min(1120, width), min(840, height))
        root.configure(bg="#f5f6fa")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(14, 8),
                        background="#ffffff", foreground="#526079", borderwidth=0)
        style.map("TButton", background=[("active", "#eeeefa")],
                  foreground=[("disabled", "#a4a9b8")])
        style.configure("Accent.TButton", background="#6355df", foreground="white",
                        font=("Segoe UI Semibold", 10), padding=(22, 10))
        style.map("Accent.TButton", background=[("disabled", "#b6b0e8"), ("active", "#5143c5")],
                  foreground=[("disabled", "#f8f7ff")])
        style.configure("TCombobox", padding=7, fieldbackground="#f5f4ff",
                        background="#f5f4ff", foreground="#5143b6", borderwidth=0,
                        arrowsize=12)
        style.map("TCombobox", fieldbackground=[("readonly", "#f5f4ff")],
                  selectbackground=[("readonly", "#f5f4ff")],
                  selectforeground=[("readonly", "#5143b6")])
        style.configure("Studio.Horizontal.TProgressbar", troughcolor="#eeedf8",
                        background="#796ae8", borderwidth=0, lightcolor="#796ae8",
                        darkcolor="#796ae8", thickness=3)

        sidebar = tk.Frame(root, bg="#151b2e", width=238)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg="#151b2e")
        brand.pack(fill="x", padx=22, pady=(28, 30))
        tk.Label(brand, text="da", bg="#7465ec", fg="white",
                 font=("Segoe UI Semibold", 17), padx=9, pady=3).pack(side="left")
        brand_text = tk.Frame(brand, bg="#151b2e")
        brand_text.pack(side="left", padx=12)
        self.label(brand_text, "Data Agent", 14, "#f6f7ff", "#151b2e").pack(anchor="w")
        self.label(brand_text, "S T U D I O", 8, "#939db7", "#151b2e").pack(anchor="w", pady=(2, 0))
        self.sidebar_button(sidebar, "+   New request", self.new_request,
                            bg="#6455dc", fg="white").pack(fill="x", padx=18, pady=(0, 24))
        self.label(sidebar, "WORKSPACE", 8, "#7e8aa6", "#151b2e").pack(anchor="w", padx=25, pady=(0, 10))
        tk.Label(sidebar, text="◈   Agent workspace", bg="#292e49", fg="#e4dfff",
                 font=("Segoe UI Semibold", 11), anchor="w", padx=17, pady=12).pack(fill="x", padx=14)
        self.sidebar_button(sidebar, "▤   Data files", self.open_data).pack(fill="x", padx=14, pady=(4, 24))
        history_header = tk.Frame(sidebar, bg="#151b2e")
        history_header.pack(fill="x", padx=25)
        self.label(history_header, "RECENT REQUESTS", 8, "#7e8aa6", "#151b2e").pack(side="left")
        self.history_count = tk.StringVar(value="0")
        tk.Label(history_header, textvariable=self.history_count, bg="#292e49", fg="#aeb8d0",
                 font=("Segoe UI", 8), padx=6).pack(side="right")
        self.history_list = tk.Listbox(sidebar, bg="#151b2e", fg="#b5bed2", borderwidth=0,
            highlightthickness=0, selectbackground="#303651", selectforeground="#ffffff",
            font=("Segoe UI", 10), activestyle="none", exportselection=False)
        self.history_list.pack(fill="both", expand=True, padx=22, pady=14)
        self.history_list.bind("<<ListboxSelect>>", self.select_history)
        bottom = tk.Frame(sidebar, bg="#1f273d", padx=14, pady=14)
        bottom.pack(fill="x", padx=18, pady=20)
        self.label(bottom, "●  Local workspace", 10, "#9ed9c3", "#1f273d").pack(anchor="w")
        self.label(bottom, "Your agents. One place.", 9, "#929fba", "#1f273d").pack(anchor="w", pady=(6, 0))

        area = tk.Frame(root, bg="#f5f6fa")
        area.pack(side="left", fill="both", expand=True)
        top = tk.Frame(area, bg="white", height=57, padx=30)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.label(top, "Workspace", 10, "#79839a", "white").pack(side="left")
        self.label(top, "  /  Overview", 10, "#27344d", "white").pack(side="left")
        tk.Label(top, text="DA", font=("Segoe UI Semibold", 10), bg="#f0edff",
                 fg="#6957cd", padx=9, pady=6).pack(side="right")
        self.label(top, "Personal workspace", 9, "#79839a", "white").pack(side="right", padx=14)
        tk.Frame(area, height=1, bg="#e8eaf1").pack(fill="x")
        body = tk.Frame(area, bg="#f5f6fa")
        body.pack(fill="both", expand=True, padx=30, pady=22)
        header = tk.Frame(body, bg="#f5f6fa")
        header.pack(fill="x")
        title = tk.Frame(header, bg="#f5f6fa")
        title.pack(side="left")
        self.label(title, "Make more of your data.", 25, "#1e2842").pack(anchor="w")
        self.label(title, "Ask a question. Build a workflow. Let your agents take it from here.",
                   10, "#7b8499").pack(anchor="w", pady=(5, 0))
        self.status = tk.StringVar(value="●  Ready")
        self.status_badge = tk.Label(header, textvariable=self.status, bg="#e4f4ed", fg="#23805d",
                 font=("Segoe UI Semibold", 9), padx=12, pady=8)
        self.status_badge.pack(side="right", anchor="n", pady=6)

        examples = tk.Frame(body, bg="#f5f6fa")
        examples.pack(fill="x", pady=(22, 20))
        examples.columnconfigure((0, 1, 2), weight=1, uniform="examples")
        presets = [
            ("01", "Explore your database", "Turn a question into an insight", "SQL", "#eeeaff", "#7860cf",
             "What are the names of the first 10 users, ordered by user_id?"),
            ("02", "Extract API data", "Bring external data into your files", "ETL", "#e3f4ef", "#328a73",
             "Extract https://pokeapi.co/api/v2/pokemon and save the results as CSV in data/extract."),
            ("03", "Transform a file", "Filter, reshape and save your data", "ETL", "#fff0e2", "#ba8248",
             "Filter data/extract/extracted_data.csv to keep venusaur only and save as CSV in data/transform."),
        ]
        for i, (number, heading, desc, mode, tint, ink, prompt) in enumerate(presets):
            card = tk.Frame(examples, bg="white", highlightbackground="#e4e7f0",
                            highlightthickness=1, padx=15, pady=12, cursor="hand2")
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0 if i == 2 else 7))
            cap = tk.Frame(card, bg="white")
            cap.pack(fill="x")
            tk.Label(cap, text=number, font=("Segoe UI Semibold", 10), bg=tint, fg=ink,
                     padx=7, pady=3).pack(side="left")
            self.label(cap, "↗", 13, "#9299ad", "white").pack(side="right")
            self.label(card, heading, 11, "#28344d", "white").pack(anchor="w", pady=(9, 4))
            self.label(card, desc, 9, "#8890a3", "white").pack(anchor="w")
            def bind_card(widget, p=prompt, m=mode):
                widget.bind("<Button-1>", lambda event: self.use_preset(p, m))
                for child in widget.winfo_children():
                    bind_card(child, p, m)
            bind_card(card)

        composer = tk.Frame(body, bg="white", highlightbackground="#e0e3ee", highlightthickness=1)
        composer.pack(fill="x")
        compose_header = tk.Frame(composer, bg="white", padx=18, pady=12)
        compose_header.pack(fill="x")
        self.label(compose_header, "YOUR REQUEST", 9, "#59647e", "white").pack(side="left")
        self.mode = tk.StringVar(value="Auto")
        self.mode_box = ttk.Combobox(compose_header, textvariable=self.mode,
            values=["Auto", "SQL", "ETL"], state="readonly", width=10, font=("Segoe UI", 9))
        self.mode_box.pack(side="right")
        self.label(compose_header, "Workflow", 9, "#9098aa", "white").pack(side="right", padx=10)
        self.prompt = ScrolledText(composer, height=3, wrap="word", font=("Segoe UI", 12),
            relief="flat", borderwidth=0, highlightthickness=0, padx=18, pady=8,
            background="white", foreground="#27344d", insertbackground="#7465dd",
            selectbackground="#e5dfff", undo=True)
        self.prompt.pack(fill="x")
        self.prompt.bind("<Control-Return>", lambda event: self.submit())
        tk.Frame(composer, height=1, bg="#f0f1f6").pack(fill="x", padx=18, pady=(10, 0))
        actions = tk.Frame(composer, bg="white", padx=18, pady=10)
        actions.pack(fill="x")
        self.label(actions, "Describe your goal, including any file paths or filters.", 9, "#9199ad", "white").pack(side="left")
        self.run_button = ttk.Button(actions, text="Run request   →", style="Accent.TButton", command=self.submit)
        self.run_button.pack(side="right")
        self.label(actions, "Ctrl + Enter", 8, "#a0a7b7", "white").pack(side="right", padx=12)
        self.progress = ttk.Progressbar(composer, mode="indeterminate", style="Studio.Horizontal.TProgressbar")
        self.progress.pack(fill="x")

        result_card = tk.Frame(body, bg="white", highlightbackground="#e0e3ee", highlightthickness=1)
        result_card.pack(fill="both", expand=True, pady=(18, 0))
        result_header = tk.Frame(result_card, bg="white", padx=18, pady=10)
        result_header.pack(fill="x")
        self.label(result_header, "Response", 12, "#26334d", "white").pack(side="left")
        self.result_title = tk.StringVar(value="Waiting for your first request")
        tk.Label(result_header, textvariable=self.result_title, bg="white", fg="#929bb0",
                 font=("Segoe UI", 9)).pack(side="left", padx=14)
        ttk.Button(result_header, text="Export ↓", command=self.save).pack(side="right")
        ttk.Button(result_header, text="Copy", command=self.copy).pack(side="right", padx=6)
        tk.Frame(result_card, height=1, bg="#edf0f6").pack(fill="x")
        self.output = ScrolledText(result_card, height=8, wrap="word", font=("Segoe UI", 11),
            relief="flat", borderwidth=0, highlightthickness=0, padx=24, pady=18,
            bg="white", fg="#536078", spacing1=3, spacing3=5, selectbackground="#e9e4ff")
        self.output.pack(fill="both", expand=True)
        self.output.tag_configure("title", font=("Segoe UI Semibold", 17), foreground="#28344d", spacing3=12)
        self.output.tag_configure("section", font=("Segoe UI Semibold", 10), foreground="#7360c8", spacing1=14, spacing3=7)
        self.output.tag_configure("code", font=("Consolas", 10), foreground="#495773", background="#f6f7fb")
        self.output.tag_configure("bullet", lmargin1=8, lmargin2=22)
        foot = tk.Frame(body, bg="#f5f6fa")
        foot.pack(fill="x", pady=(10, 0))
        self.label(foot, "Each request starts a fresh workflow.", 8, "#929aaf").pack(side="left")
        self.label(foot, "Powered by your agents · API usage applies", 8, "#929aaf").pack(side="right")
        self.show("Ready when you are.\n\nChoose a workflow above or write your own request. Your answer will appear here, with a query and review when you select SQL mode.\n\n• Explore users, rides and payments in your database.\n• Extract data from an API into a local file.\n• Transform a dataset into something useful.")
        root.after(100, self.poll)

    def sidebar_button(self, parent, text, command, bg="#151b2e", fg="#b5bed2"):
        button = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
            activebackground="#343252", activeforeground="white", relief="flat", borderwidth=0,
            font=("Segoe UI Semibold", 10), padx=16, pady=11, anchor="w", cursor="hand2")
        button.bind("<Enter>", lambda event: button.configure(bg="#343252"))
        button.bind("<Leave>", lambda event: button.configure(bg=bg))
        return button

    def use_preset(self, text, mode):
        if not self.busy:
            self.mode.set(mode)
            self.fill(text)

    def new_request(self):
        if not self.busy:
            self.fill("")
            self.mode.set("Auto")
            self.history_list.selection_clear(0, "end")
            self.result_title.set("New request")
            self.status.set("●  Ready")
            self.status_badge.configure(bg="#e4f4ed", fg="#23805d")
            self.show("What would you like to explore?\n\nDescribe your goal above, or choose one of the starter workflows.")

    @staticmethod
    def label(parent, text, size=11, fg="#14213d", bg="#f3f5f9"):
        return tk.Label(parent, text=text, font=("Segoe UI", size), fg=fg, bg=bg)

    def fill(self, text):
        if not self.busy:
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", text)
            self.prompt.focus_set()

    def show(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        in_code = False
        for i, line in enumerate(text.splitlines()):
            tag = ""
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                tag = "code"
            elif line.startswith("#"):
                line = line.lstrip("#").strip()
                tag = "title" if i == 0 else "section"
            elif line in ("SQL QUERY", "REVIEW"):
                tag = "section"
            elif line.startswith(("•", "- ")):
                tag = "bullet"
            elif i == 0:
                tag = "title"
            self.output.insert("end", line + "\n", tag)
        self.output.configure(state="disabled")

    def submit(self):
        question = self.prompt.get("1.0", "end").strip()
        if self.busy or not question:
            return
        self.busy = True
        self.started = time.monotonic()
        mode = self.mode.get()
        self.run_button.configure(state="disabled")
        self.mode_box.configure(state="disabled")
        self.prompt.configure(state="disabled")
        self.status.set("●  Working…")
        self.status_badge.configure(bg="#eeebff", fg="#6550bd")
        self.result_title.set("RUNNING / " + mode.upper())
        self.show("Your agent is working. The result will appear here.")
        self.progress.start(12)
        threading.Thread(target=self.work, args=(question, mode), daemon=True).start()

    def work(self, question, mode):
        try:
            result = self.runner(question, mode)
            self.events.put((True, question, result))
        except Exception as exc:
            # Keep credentials and raw request bodies out of the interface.
            from dotenv import dotenv_values
            error = str(exc)
            for key, value in dotenv_values(ROOT / ".env").items():
                if value and any(word in key.lower() for word in ("password", "secret", "key", "token")):
                    error = error.replace(value, "[hidden]")
            self.events.put((False, question, {"answer": type(exc).__name__ + ": " + error, "route": mode}))

    def poll(self):
        try:
            success, question, result = self.events.get_nowait()
        except queue.Empty:
            if self.busy:
                self.status.set(f"Working · {int(time.monotonic() - self.started)}s")
        else:
            self.busy = False
            self.progress.stop()
            self.run_button.configure(state="normal")
            self.mode_box.configure(state="readonly")
            self.prompt.configure(state="normal")
            elapsed = round(time.monotonic() - self.started, 1)
            self.status.set("●  Complete" if success else "●  Needs attention")
            self.status_badge.configure(bg="#e4f4ed" if success else "#fff0e6", fg="#23805d" if success else "#b56a31")
            self.result_title.set(f"{result['route']} / {elapsed}s" + ("" if success else " / ERROR"))
            text = result["answer"] or "The agent returned no answer."
            if result.get("sql"):
                text += "\n\nSQL QUERY\n" + result["sql"]
                text += "\n\nREVIEW\n" + str(result.get("safe")) + " · " + result.get("review", "")
            if not success:
                text = "The request could not be completed.\n\n" + text + "\n\nCheck your .env configuration and service availability before retrying. ETL files may already have been written; check the data folder."
            self.history.append((question, text, self.result_title.get()))
            self.history_list.insert("end", f"{len(self.history):02d}   {question[:22]}")
            self.history_count.set(str(len(self.history)))
            self.show(text)
        self.root.after(100, self.poll)

    def select_history(self, event=None):
        if self.busy or not self.history_list.curselection():
            return
        question, text, title = self.history[self.history_list.curselection()[0]]
        self.fill(question)
        self.result_title.set(title)
        self.show(text)

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.output.get("1.0", "end-1c"))

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="agent-result.txt", filetypes=[("Text", "*.txt")])
        if path:
            try:
                Path(path).write_text(self.output.get("1.0", "end-1c"), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Could not save", str(exc))

    def open_data(self):
        folder = ROOT / "data"
        folder.mkdir(exist_ok=True)
        os.startfile(str(folder))

    def close(self):
        if self.busy:
            messagebox.showinfo("Request in progress", "Wait for the current request to finish before closing. Closing a window cannot undo an API call or file operation.")
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="AI Data Agent desktop and command line")
    parser.add_argument("--question", help="Run one request in the terminal instead of opening the window")
    parser.add_argument("--mode", choices=["Auto", "SQL", "ETL"], default="Auto")
    args = parser.parse_args()
    # The existing tools use relative file paths.
    os.chdir(ROOT)
    if args.question:
        print(json.dumps(run_request(args.question, args.mode), indent=2, ensure_ascii=False))
    else:
        root = tk.Tk()
        Workspace(root)
        root.mainloop()


if __name__ == "__main__":
    main()
