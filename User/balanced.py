import sublime, sublime_plugin

#TODO: write balanced function
#TODO: cache balanced-ness until view is modified

class InputStateTracker(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "balanced_pairs":
            print "checking if pairs are balanced"
            v = False

            if not v:
                sublime.status_message("Balanced is deactivated until balanced pairs are fixed...")

            if operator == sublime.OP_EQUAL:
                return v == operand
            elif operator == sublime.OP_NOT_EQUAL:
                return v != operand
        return None


class MovePastCharCommand(sublime_plugin.TextCommand):
    def run(self, edit, char):
        print "moving past char: %s" % char
        new_sels = []
        sels = self.view.sel()
        for sel in sels:
            region = self.view.find(char, sel.begin(), sublime.LITERAL)
            new_sels.append(sublime.Region(region.end()))

        sels.clear()
        for sel in new_sels:
            sels.add(sel)
