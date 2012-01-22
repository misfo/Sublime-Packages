import re, os, socket, string, sublime, sublime_plugin, threading
from functools import partial

max_cols = 60

def clean(str):
    return str.translate(None, '\r') if str else None

def symbol_char(char):
    return re.match("[-\w*+!?/.<>]", char)

def classpath_relative_path(file_name):
    (abs_path, ext) = os.path.splitext(file_name)
    segments = []
    while 1:
        (abs_path, segment) = os.path.split(abs_path)
        if segment == "src": return string.join(segments, "/")
        segments.insert(0, segment)

def find_repl_port(clj):
    match = re.search(r":repl-port[\s\n]+(\d+)", clj)
    return match.group(1) if match else None

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

def call_after_thread_dies(func, thread):
    if thread.is_alive():
        sublime.set_timeout(partial(call_after_thread_dies, func, thread), 100)
    else:
        func()

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

class Repler(threading.Thread):
    def __init__(self, sock, exprs):
        threading.Thread.__init__(self)
        self.sock = sock
        self.exprs = exprs

    def _send(self, expr):
        if expr: self.sock.send(expr + "\n")
        output = "" # TODO use buffer instead?
        while 1:
            output += self.sock.recv(1024)
            match = re.match(r"(.*\n)?(\S+)=> $", output, re.DOTALL)
            if match: return (clean(match.group(1)), match.group(2))

    def run(self):
        self.results = []

        _, ns = self._send(None)

        for expr in self.exprs:
            output, next_ns = self._send(expr)
            self.results.append({'ns': ns, 'expr': expr, 'output': output})
            ns = next_ns

        self.sock.close()
        self.resulting_ns = ns


class ClojureEvaluate(sublime_plugin.TextCommand):
    def _repl_port_number(self):
        window = self.view.window()
        folders = window.folders()
        file_name = self.view.file_name()
        try:
            # FIXME doesn't work for non-file buffers
            proj_folder = (f for f in folders if file_name.startswith(f)).next()
        except StopIteration:
            exit_with_error("No folder open containing " + file_name)

        project_clj_file_name = os.path.join(proj_folder, 'project.clj')
        try:
            project_clj = open(project_clj_file_name, 'r').read()
        except IOError:
            exit_with_error("No project.clj found in " + proj_folder)

        repl_port = find_repl_port(project_clj)
        if repl_port:
            return int(repl_port)
        else:
            exit_with_error("No :repl-port specified in "
                            + project_clj_file_name)

    def run(self, edit,
            expr,
            in_panel = False,
            input_default = None,
            input_prompt = None,
            output = '$output',
            syntax_file = 'Packages/Clojure/Clojure.tmLanguage',
            view_name = '$expr'):
        self._window = self.view.window()
        self._expr = expr
        self._in_panel = in_panel
        self._input_default = input_default
        self._output = output
        self._syntax_file = syntax_file
        self._view_name = view_name
        port = self.view.settings().get('clojure_repl_port')
        repl_ns = None

        if not port:
            port = self._repl_port_number()
            self.view.settings().set('clojure_repl_port', port)

        try:
            self._sock = socket.socket()
            self._sock.connect(('localhost', port))
            self._sock.settimeout(10)
        except socket.error:
            exit_with_error("No repl is listening on port " + str(port)
                            + "\nPlease start one with `lein repl`")

        if re.search(r"\$\{?from_input_panel\}?", expr):
            view = self._window.show_input_panel(input_prompt, "",
                                                 self._handle_input, None, None)
        else:
            self._handle_input(None)

    def _handle_input(self, from_input_panel):
        if from_input_panel == "":
            from_input_panel = self._input_default

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

        self._thread = Repler(self._sock, exprs)
        self._thread.start()
        call_after_thread_dies(self._handle_results, self._thread)

    def _handle_results(self):
        if self._in_panel:
            view = self._window.get_output_panel('clojure_output')
        else:
            view = self._window.new_file()
            view.set_scratch(True)
            view.settings().set('scroll_past_end', True)
            view.set_read_only(True)

        if self._syntax_file:
            view.set_syntax_file(self._syntax_file)

        result = self._thread.results[-1]
        template = string.Template(self._output)
        output_to_view(view, template.safe_substitute(result))

        if self._in_panel:
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
