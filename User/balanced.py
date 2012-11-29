import sublime, sublime_plugin

#TODO: cache balanced-ness until view is modified
#TODO: end paren should skip over balanced pairs
#TODO: keybindings should be disabled within comments, strings

delims = {'(': ')'}
close_delims = frozenset(delims.values())

def braces(code, ignored_regions=[], parse_state={'position': 0, 'stack': []}):
    bs = []
    ignore_iter = iter(ignored_regions)
    stack = list(parse_state['stack'])
    i = parse_state['position']

    ignore = None
    try:
        ignore = ignore_iter.next()
    except StopIteration:
        pass

    while True:
        if ignore and ignore.contains(i):
            i = ignore.end()
            try:
                ignore = ignore_iter.next()
            except StopIteration:
                ignore = None

        try:
            char = code[i]
        except IndexError:
            new_state = parse_state.copy()
            new_state['position'] = i
            new_state['stack'] = stack
            return (bs, new_state)

        if char in delims:
            stack.append(char)
            bs.append((char, i))
        elif char in close_delims:
            expected_delim = None
            try:
                expected_delim = delims[stack.pop()]
            except IndexError:
                pass

            if char == expected_delim:
                bs.append((char, i))
            else:
                raise Exception("Unexpected %s at %s" % (char, i))

        i += 1

def is_balanced(code, ignored_regions=[]):
    try:
        (_, state) = braces(code, ignored_regions)
        return len(state['stack']) == 0
    except:
        return False

class InputStateTracker(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "balanced_pairs":
            print "checking if pairs are balanced"

            nchars = view.size()
            code = view.substr(sublime.Region(0, nchars))
            ignored_regions = view.find_by_selector('comment,string')
            v = is_balanced(code, ignored_regions)

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
