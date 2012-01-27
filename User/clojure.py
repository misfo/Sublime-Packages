import re, os, socket, string, subprocess, thread, threading, time
import sublime, sublime_plugin
from functools import partial

max_cols = 60

def clean(str):
    return str.translate(None, '\r') if str else None

def symbol_char(char):
    return re.match("[-\w*+!?/.<>]", char)

def project_path(dir_name):
    if os.path.isfile(os.path.join(dir_name, 'project.clj')):
        return dir_name
    else:
        return project_path(os.path.split(dir_name)[0])

def classpath_relative_path(file_name):
    (abs_path, ext) = os.path.splitext(file_name)
    segments = []
    while 1:
        (abs_path, segment) = os.path.split(abs_path)
        if segment == "src": return string.join(segments, "/")
        segments.insert(0, segment)

def output_to_view(v, text):
    v.set_read_only(False)
    edit = v.begin_edit()
    v.insert(edit, v.size(), text)
    v.end_edit(edit)
    v.set_read_only(True)

def exit_with_status(message):
    sublime.status_message(message)
    sys.exit(1)

def exit_with_error(message):
    sublime.error_message(message)
    sys.exit(1)

def new_sock(port):
    print "port", port
    sock = socket.socket()
    sock.connect(('localhost', port))
    sock.settimeout(10)
    return sock

def send(sock, expr):
    if expr: sock.send(expr + "\n")
    output = "" # TODO use buffer instead?
    while 1:
        output += sock.recv(1024)
        match = re.match(r"(.*\n)?(\S+)=> $", output, re.DOTALL)
        if match: return (clean(match.group(1)), match.group(2))

# indexed by window id
repls = {}

class REPL:
    def __init__(self, proc):
        self.proc = proc
        self.port = None
        self.persistent_sock = None
        self.ns = None
        self.view = None

    def connect_sock(self):
        stdout, stderr = self.proc.communicate()
        match = re.search(r"server listening on localhost port (\d+)", stdout)
        if match:
            self.port = int(match.group(1))
            self.persistent_sock = new_sock(self.port)
            status = "Clojure REPL started on port " + str(self.port)
            sublime.set_timeout(partial(sublime.status_message, status), 0)
        else:
            exit_with_error("Unable to start a REPL with `lein repl`")

    def evaluate(self, exprs, persistent, on_complete):
        print "possibly sleeping"
        while not self.persistent_sock:
            time.sleep(0.1)
        print "done sleeping"
        sock = self.persistent_sock if persistent else new_sock(self.port)

        ns = self.ns
        if not ns or not persistent:
            _, ns = send(sock, None)

        results = []
        for expr in exprs:
            output, next_ns = send(sock, expr)
            results.append({'ns': ns, 'expr': expr, 'output': output})
            ns = next_ns

        if persistent:
            self.ns = ns

        sublime.set_timeout(partial(on_complete, results), 0)

class LazyViewString:
    def __init__(self, view):
        self.view = view

    def __str__(self):
        if not hasattr(self, '_string_value'):
            self._string_value = self.get_string()
        return self._string_value

class Selection(LazyViewString):
    def get_string(self):
        sel = self.view.sel()
        if len(sel) == 1:
            return self.view.substr(self.view.sel()[0]).strip()
        else:
            exit_with_status("There must be one selection to evaluate")

class SymbolUnderCursor(LazyViewString):
    def get_string(self):
        begin = end = self.view.sel()[0].begin()
        while symbol_char(self.view.substr(begin - 1)): begin -= 1
        while symbol_char(self.view.substr(end)): end += 1
        if begin == end:
            exit_with_status("No symbol found under cursor")
        else:
            return self.view.substr(sublime.Region(begin, end))

class ClojureStartRepl(sublime_plugin.WindowCommand):
    def run(self):
        if hasattr(self, 'repl'):
            print "repl already alive", self.repl
            return

        sublime.status_message("Starting Clojure REPL")
        #FIXME don't use active view
        file_name = self.window.active_view().file_name()
        cwd = None
        if file_name:
            cwd = project_path(os.path.split(file_name)[0])
        else:
            for folder in self.window.folders():
                cwd = project_path(folder)
                if cwd: break

        proc = subprocess.Popen(["lein", "repl"], stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE,
                                                  cwd=cwd)
        self.repl = REPL(proc)
        repls[self.window.id()] = self.repl
        thread.start_new_thread(self.repl.connect_sock, ())

class ClojureEvaluate(sublime_plugin.TextCommand):
    def run(self, edit,
            expr,
            input_panel = None,
            syntax_file = 'Packages/Clojure/Clojure.tmLanguage',
            view_name = '$expr',
            **kwargs):
        self._window = self.view.window()
        self._expr = expr
        self._syntax_file = syntax_file
        self._view_name = view_name
        self._window.run_command('clojure_start_repl')

        if input_panel:
            it = input_panel['initial_text']
            on_done = partial(self._handle_input, **kwargs)
            view = self._window.show_input_panel(input_panel['prompt'],
                                                 "".join(it) if it else "",
                                                 on_done, None, None)

            if it and len(it) > 1:
                view.sel().clear()
                offset = 0
                for chunk in it[0:-1]:
                    offset += len(chunk)
                    view.sel().add(sublime.Region(offset))
        else:
            self._handle_input(None, **kwargs)

    def _handle_input(self, from_input_panel, output_to = "repl", **kwargs):
        template = string.Template(self._expr)
        expr = template.safe_substitute({
            "from_input_panel": from_input_panel,
            "selection": Selection(self.view),
            "symbol_under_cursor": SymbolUnderCursor(self.view)})

        exprs = []
        file_name = self.view.file_name()
        if file_name:
            path = classpath_relative_path(file_name)
            file_ns = re.sub("/", ".", path)
            exprs.append("(do (load \"/" + path + "\") "
                         + "(in-ns '" + file_ns + "))")
        exprs.append(expr)

        repl = repls[self._window.id()]
        print "about to evaluate", exprs
        persistent = output_to == "repl"
        on_complete = partial(self._handle_results,
                              output_to = output_to,
                              **kwargs)
        thread.start_new_thread(repl.evaluate,
                                (exprs, persistent, on_complete))

    def _handle_results(self, results, output_to, output = '$output'):
        print "got results", results
        if output_to == "panel":
            view = self._window.get_output_panel('clojure_output')
        elif output_to == "view":
            view = self._window.new_file()
            view.set_scratch(True)
            view.set_read_only(True)
        else:
            repl = repls[self._window.id()]
            print "repl.view", repl.view
            if repl.view: print "repl.view.window()", repl.view.window()
            if not repl.view:
                repl.view = self._window.new_file()
                repl.view.set_scratch(True)
                repl.view.set_read_only(True)
                repl.view.settings().set('scroll_past_end', True)

            view = repl.view

        if self._syntax_file:
            view.set_syntax_file(self._syntax_file)

        result = results[-1]
        template = string.Template(output)
        output_to_view(view, template.safe_substitute(result))

        if output_to == "panel":
            self._window.run_command("show_panel",
                                     {"panel": "output.clojure_output"})
        else:
            view.sel().clear()
            view.sel().add(sublime.Region(0))

            view_name_template = string.Template(self._view_name)
            view.set_name(view_name_template.safe_substitute(result))

            active_view = self._window.active_view()
            active_group = self._window.active_group()
            repl_view_group, _ = self._window.get_view_index(view)
            self._window.focus_view(view)
            if repl_view_group != active_group:
                # give focus back to the originally active view if it's in a
                # different group
                self._window.focus_view(active_view)

            view.set_viewport_position(view.text_to_layout(0))
