import re, os, socket, string, sublime, sublime_plugin

port = 46167

def clean(str):
	return str.translate(None, '\r') if str else None

def symbol_char(char):
	return re.match("[-\w*+!?/.]", char)

def classpath_relative_path(file_name):
	(abs_path, ext) = os.path.splitext(file_name)
	segments = []
	while 1:
		(abs_path, segment) = os.path.split(abs_path)
		if segment == "src": return string.join(segments, "/")
		segments.insert(0, segment)

def output_to_view(v, output):
	edit = v.begin_edit()
	v.insert(edit, 0, output)
	v.end_edit(edit)

class LeinReplSocket:
	def __init__(self):
		self.sock = socket.socket()
		self.sock.connect(('localhost', port))
		self.sock.settimeout(2)

	def send(self, expr):
		if expr: self.sock.send(expr + "\n")
		output = "" # TODO use buffer instead?
		while 1:
			output += self.sock.recv(1024)
			match = re.match(r"(.*\n)?(\S+=> )$", output, re.DOTALL)
			if match: return (clean(match.group(1)), match.group(2))

	def close(self):
		self.sock.close()


class ClojureReplCommand(sublime_plugin.TextCommand):
	def _symbol_under_cursor(self):
		begin = end = self.view.sel()[0].begin()
		while symbol_char(self.view.substr(begin - 1)): begin -= 1
		while symbol_char(self.view.substr(end)): end += 1
		return self.view.substr(sublime.Region(begin, end))

	def _output_to_buffer(self, name, output):
		v = self.view.window().new_file()
		v.set_name(name)
		v.set_scratch(True)
		v.set_syntax_file('Packages/Clojure/Clojure.tmLanguage')
		output_to_view(v, output)

	def _output_to_panel(self, output):
		v = self.view.window().get_output_panel('clojure_output')
		output_to_view(v, output)
		self.view.window().run_command("show_panel", {"panel": "output.clojure_output"})

	def _socket_send(self, edit, expr, use_buffer = False, strip_nil_return = False):
		s = LeinReplSocket()

		(output, prompt) = s.send(None)
		print "prompt before everything", prompt

		file_name = self.view.file_name()
		if file_name:
			path = classpath_relative_path(file_name)
			(output, prompt) = s.send("(load \"/" + path + "\")")
			print "output", output

			print "prompt before in-ns", prompt
			(output, prompt) = s.send("(in-ns '" + re.sub("/", ".", path) + ")")
			print "output", output

		print "prompt before expr", prompt
		(output, _) = s.send(expr)

		s.close()

		if not output:
			self._output_to_panel("There was an error while executing " + expr)
			return

		if strip_nil_return:
			output = re.sub(r"\nnil$", "", output)

		if use_buffer:
			self._output_to_buffer(expr, output)
		else:
			self._output_to_panel(prompt + expr + "\n" + output)

class SymbolDocumentation(ClojureReplCommand):
	def run(self, edit):
		symbol = self._symbol_under_cursor()
		if not symbol: return
		self._socket_send(edit, "(clojure.repl/doc " + symbol + ")")

class SymbolSource(ClojureReplCommand):
	def run(self, edit):
		symbol = self._symbol_under_cursor()
		if not symbol: return
		self._socket_send(edit, "(clojure.repl/source " + symbol + ")", use_buffer = True, strip_nil_return = True)
