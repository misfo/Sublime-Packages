import time
import sublime, sublime_plugin

#TODO: cache balanced-ness until view is modified
#TODO: end paren should skip over balanced pairs
#TODO: keybindings should be disabled within comments, strings

delims = {'(': ')'}
close_delims = frozenset(delims.values())

def index_ranges(view_size, ignored_regions):
    if len(ignored_regions):
        ranges = []
        next_included = 0

        for ignored in ignored_regions:
            first_ignored = ignored.begin()
            if first_ignored > next_included:
                ranges.append(xrange(next_included, first_ignored))
            next_included = ignored.end()

        if next_included < view_size:
            ranges.append(xrange(next_included, view_size))

        return ranges
    else:
        return [xrange(view_size)]

def braces(code, ignored_regions=[], parse_state={'position': 0, 'stack': []}):
    bs = []
    stack = list(parse_state['stack'])
    i = parse_state['position']

    ranges = index_ranges(len(code), ignored_regions)

    for indexes in ranges:
        for i in indexes:
            char = code[i]

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

    new_state = parse_state.copy()
    new_state['position'] = i
    new_state['stack'] = stack
    return (bs, new_state)

def is_balanced(code, ignored_regions=[]):
    try:
        (_, state) = braces(code, ignored_regions)
        return len(state['stack']) == 0
    except:
        return False

class InputStateTracker(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "balanced_pairs":
            nchars = view.size()
            code = view.substr(sublime.Region(0, nchars))
            ignored_regions = view.find_by_selector('comment,string')

            start = time.time()
            v = is_balanced(code, ignored_regions)
            elapsed = time.time() - start
            print "checked if pairs were balanced in %f" % elapsed

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
