#################################################
### cleaning/extracting/adjusting source code ###
#################################################

from functools import partial
from inspect import currentframe, findsource, getsource, signature, getgeneratorstate
from itertools import chain
from sys import version_info
from types import CodeType, CellType, FunctionType, GeneratorType# , FrameType ## lineno_adjust
from typing import Iterable, Union

## to ensure gcopy.custom_generator.Generator can be used in exec for sign ##
from gcopy.track import get_indent, track_adjust
from gcopy.utils import (
    attr_cmp,
    cli_findsource,
    code_cmp,
    empty_generator,
    get_nonlocals,
    getcode,
    getframe,
    is_cli,
    skip,
    try_set,
)


def update_depth(depth: int, char: str, selection: tuple[str, str] = ("(", ")")) -> int:
    """Updates the depth of brackets"""
    if char in selection[0]:
        depth += 1
    elif char in selection[1]:
        depth -= 1
    return depth


## only required when using compound statements ##
# def lineno_adjust(frame: FrameType) -> int:
#     """
#     unpacks a line of compound statements
#     into lines up to the last instruction
#     that determines the adjustment required
#     """
#     line, current_lineno, instructions = (
#         [],
#         frame.f_lineno,
#         get_instructions(frame.f_code),
#     )
#     ## get the instructions at the lineno ##
#     for instruction in instructions:
#         lineno, obj = instruction.positions.lineno, (
#             list(instruction.positions[2:]),
#             instruction.offset,
#         )
#         if not None in obj[0] and lineno == current_lineno:
#             ## exhaust the iter to get all the lines ##
#             line = [obj]
#             for instruction in instructions:
#                 lineno, obj = instruction.positions.lineno, (
#                     list(instruction.positions[2:]),
#                     instruction.offset,
#                 )
#                 if lineno != current_lineno:
#                     break
#                 line += [obj]
#             break
#     ## combine the lines until f_lasti is encountered to return how many lines ##
#     ## futher from the current line would the offset be if split up into lines ##
#     if line:
#         index, current, lasti = 0, [0, 0], frame.f_lasti
#         line.sort()
#         for pos, offset in line:
#             if offset == lasti:
#                 return index
#             if pos[0] > current[1]:  ## independence ##
#                 current = pos
#                 index += 1
#             elif pos[1] > current[1]:  ## intersection ##
#                 current[1] = pos[1]
#     raise ValueError("f_lasti not encountered")


def line_adjust(line: str, lines: list[str], adjust: bool = True) -> str:
    """
    Adds indentation to the lines and colon for statements

    Specific to the unpack_genexpr function where the lines
    will start with 'for' or 'if' when separated

    Note: no need to check for next_char since this is done
    before calling this function
    """
    indent, new_line = " " * 4, ""
    if adjust:
        if line.startswith("if"):
            index = 2
        else:
            index = 3
        new_line, line = line[-index:] + " ", line[:-index]
    line = line.strip()
    ## needed for the first segment that will have no for/if ##
    if line.startswith("for") or line.startswith("if"):
        line += ":"
    return new_line, lines + [indent * len(lines) + line]


def update_line(
    index: int,
    char: str,
    line: str,
    source_iter: Iterable,
    prev: tuple[int, int, str],
    depth: int,
) -> tuple[str, int, tuple[int, int, str]]:
    """Updates the current line specific to unpack_genexpr"""
    if char == "\\":
        line += " "  ## incase it doesn't have any gap ##
    if char in "\\\n":
        return
    ## collect strings
    if char == "'" or char == '"':
        line, prev, _ = string_collector_proxy(index, char, prev, source_iter, line)
        return
    ## we're only interested in when the generator expression ends in terms of the depth ##
    depth = update_depth(depth, char)
    ## accumulate the current line
    line += char
    return line, depth, prev


def unpack_genexpr(source: str) -> list[str]:
    """unpacks a generator expressions' for loops into a list of source lines"""
    lines, line, ID, depth, prev, passed_first_for = (
        [],
        "",
        "",
        0,
        (0, 0, ""),
        False,
    )
    source_iter = enumerate(source[1:-1])
    for index, char in source_iter:
        args = update_line(index, char, line, source_iter, prev, depth)
        if args is None:
            continue
        line, depth, prev = args
        if depth == 0:
            ## collect IDs
            if char.isalnum():
                ID += char
                if ID == "for" or (ID == "if" and passed_first_for):
                    try:
                        next_char = next(source_iter)[1]
                    ## it's not possible to have i.e. ( ... if char == if) ##
                    except StopIteration:
                        raise SyntaxError("Unexpected format encountered")
                    ## adjusts and adds the line to lines ##
                    if next_char in "\\ ":
                        line, lines = line_adjust(line, lines)
                        if not passed_first_for and lines:
                            passed_first_for = True
                    ## otherwise adds to the current line ##
                    else:
                        args = update_line(index, char, line, source_iter, prev, depth)
                        if args is None:
                            continue
                        line, depth, prev = args
                        ID = ""
            else:
                ID = ""
    _, lines = line_adjust(line, lines, False)
    return lines[1:] + [" " * (4 * len(lines)) + "return " + lines[0]]


def skip_line_continuation(source_iter: Iterable, source: str, index: int) -> int:
    """skips line continuations in source"""
    whitespace = get_indent(source[index + 1 :])  ## +1 since 'index:' is inclusive ##
    ## skip the whitespace after newline ##
    ## skip the current char, whitespace, newline and whitespace after ##
    index += whitespace + 1 + get_indent(source[index + 1 + whitespace + 1 :])
    skip(source_iter, index)
    return index


def skip_source_definition(source: str) -> str:
    """Skips the function definition and decorators in the source code"""
    ID, source_iter = "", enumerate(source)
    for index, char in source_iter:
        ## skip decorators ##
        while char == "@":
            while char != "\n":
                index, char = next(source_iter)
            index, char = next(source_iter)
        ## collect the ID ##
        if char.isalnum():
            ID += char
        else:
            if ID == "def" and char in " \\":
                while char != "(":
                    index, char = next(source_iter)
                break
            ID = ""
    ## skip to the end of the function definition ##
    depth = 1
    for index, char in source_iter:
        if char == ":" and depth == 0:
            return source[index + 1 :]
        depth = update_depth(depth, char, ("([{", ")]}"))
    raise SyntaxError("Unexpected format encountered")


def collect_string(
    source_iter: Iterable, index: int, reference: str, source: str = None
) -> tuple[int, Union[str, list[str]], int]:
    """
    Collects strings in an iterable assuming correct
    python syntax and the char before is a qoutation mark

    Note: make sure source_iter is an enumerated type
    """
    line, backslash, left_brace, lines, fixed_lines = reference, False, 0, [], 0
    for index, char in source_iter:
        if char == "\n":
            fixed_lines += 1
        ## detect f-strings for value yields ##
        if source and char == "{" or left_brace:
            if char != "{" and left_brace % 2:
                ## we could check for yields before unpacking but this is maybe more efficient ##
                ## especially since you can have f-strings within f-strings ##
                adjustments, f_string_contents, _, fixed_lines = unpack(
                    char,
                    source_iter,
                    source,
                    True,
                    index=index,
                    fixed_lines=fixed_lines,
                )
                ## update ##
                lines += adjustments
                line += f_string_contents
                left_brace = 0
                continue
            left_brace += 1
        if char == reference and not backslash:
            line += char
            break
        line += char
        backslash = False
        if char == "\\":
            backslash = True
    if source:
        return (
            index,
            lines + [line],
            fixed_lines,
        )  ## we have to add it for the f-string case ##
    return index, line, fixed_lines


def collect_multiline_string(
    source_iter: Iterable, index: int, reference: str, source: str = None
) -> tuple[int, Union[str, list[str]], int]:
    """
    Collects multiline strings in an iterable assuming
    correct python syntax and the char before is a
    qoutation mark

    Note: make sure source_iter is an enumerated type

    if a string starts with 3 qoutations
    then it's classed as a multistring
    """
    line, backslash, prev, count, left_brace, lines, fixed_lines = (
        reference,
        False,
        -2,
        0,
        0,
        [],
        0,
    )
    for index, char in source_iter:
        if char == "\n":
            fixed_lines += 1
        ## detect f-strings for value yields ##
        if source and char == "{" or left_brace:
            if char != "{" and left_brace % 2:
                ## we could check for yields before unpacking but this is maybe more efficient ##
                adjustments, f_string_contents, _, fixed_lines = unpack(
                    char,
                    source_iter,
                    source,
                    True,
                    index=index,
                    fixed_lines=fixed_lines,
                )
                ## update ##
                lines += adjustments
                line += f_string_contents
                left_brace = 0
                continue
            left_brace += 1
        if char == reference and not backslash:
            if index - prev == 1:
                count += 1
            else:
                count = 0
            prev = index
            if count == 2:
                line += char
                break
        line += char
        backslash = False
        if char == "\\":
            backslash = True
    if source:
        return (
            index,
            lines + [line],
            fixed_lines,
        )  ## we have to add it for the f-string case ##
    return index, line, fixed_lines


def string_collector_proxy(
    index: int,
    char: str,
    prev: tuple[int, int, str],
    iterable: Iterable,
    line: str = None,
    f_string: bool = False,
) -> tuple[str, tuple[int, int, str], list[str], int]:
    """Proxy function for usage when collecting strings since this block of code gets used repeatedly"""
    ## get the string collector type ##
    if prev[0] + 2 == prev[1] + 1 == index and prev[2] == char:
        string_collector, temp_index = collect_multiline_string, 3
    else:
        string_collector, temp_index = collect_string, 1
    ## determine if we need to look for f-strings in case of value yields ##
    source = None
    if f_string and version_info >= (3, 6) and len(line) >= temp_index and line[-temp_index] == "f":
        ## use the source to determine the extractions ##
        ## +1 to move one forwards from the 'f' ##
        source = line[1 - temp_index :]
    temp_index, temp_line, fixed_lines = string_collector(iterable, index, char, source)
    prev = (index, temp_index, char)
    if f_string:
        if source:
            ## lines (adjustments) + line (string collected) ##
            return temp_line.pop(), prev, temp_line, fixed_lines
        return temp_line, prev, [], fixed_lines
    if line is not None:
        line += temp_line
    return line, prev, fixed_lines


def inverse_bracket(bracket: str) -> Union[str, None]:
    """Gets the inverse of the current bracket"""
    ## use .get(..., None) since char == '' is possible ##
    return {
        "(": ")",
        ")": "(",
        "{": "}",
        "}": "{",
        "[": "]",
        "]": "[",
    }.get(bracket, None)


def named_adjust(
    line: str,
    lines: list[str],
    final_line: str,
    line_iter: Iterable,
    ID: str,
    source: str = "",
    index: int = 0,
    depth_total: int = 0,
    depths: dict = {},
    fixed_lines: int = 0,
) -> tuple[str, list[str], str, dict]:
    """
    Adjusts the lines and final line for named expressions
    and named expressions within named expressions

    a = (b:=next(j)) = c

    next(j)
    b = next(j)
    """
    line += ":="
    ## skip the next iteration to the '=' char ##
    ## for ':=' you can't have ': =' or ':\=' ##
    next(line_iter)
    ## this should mean that we can just unwrap it. ##
    ## If the named expression is a dictionary then ##
    ## it will be the last line added to the new lines ##
    temp = []
    if ID and lines:
        temp = [lines.pop()]
    line, lines, final_line, named, depths, fixed_lines = update_lines(
        line,
        lines,
        final_line,
        True,
        line_iter,
        source=source,
        index=index,
        depth_total=depth_total,
        depths=depths,
        fixed_lines=fixed_lines,
    )
    lines += temp
    return line, lines, final_line, depths, fixed_lines


def unpack_adjust(line: str) -> list[str]:
    """
    adjusts the unpacked line for usage and value yields
    
    Note:
    make sure to run .strip() on the line first
    """
    if line.startswith("yield ") or line.startswith("yield)") or line == "yield":
        return yield_adjust(line, "") + ["locals()['.internals']['.args'] += [locals()['.internals']['.send']]"]
    ## adjust to clean up the brackets ##
    if not is_item(line):
        end_char = line[-1:]
        if end_char in "}])":
            char = line[0:1]
            if char.isalnum() or (char in "([{" and inverse_bracket(char) != end_char):
                for char in line[::-1]:
                    if char != end_char:
                        break
                    line = line[:-1]
    return ["locals()['.internals']['.args'] += [%s]" % line]


operators = ",<=>/|+-*&%@^"


def update_lines(
    line: str,
    lines: list[str],
    final_line: str,
    named: bool = False,
    unwrap: Union[Iterable, None] = None,
    bracket_index: int = None,
    operator: str = "",
    yielding: bool = False,
    source: str = "",
    index: int = 0,
    depth_total: int = 0,
    depths: dict = {},
    fixed_lines: int = 0,
) -> tuple[str, list[str], str, bool, dict]:
    """
    adds the current line or the unwrapped line to the lines
    if it's not a variable or constant otherwise the line is
    added to the final lines
    """
    if not line.isspace():
        ## unwrapping ## - for brackets
        if unwrap is not None:
            temp_lines, temp_final_line, _, fixed_lines = unpack(
                source_iter=unwrap,
                source=source,
                unwrapping=True,
                named=named,
                index=index,
                # depth_total=depth_total,
                # depths=depths,
                fixed_lines=fixed_lines,
            )
            if yielding:
                ## we have to :-1 since the end bracket gets added ##
                temp_final_line = "yield " + temp_final_line[:-1]
                try_set(depths.get(depth_total, None), -1, len(lines))
                lines += temp_lines + unpack_adjust(temp_final_line.strip())
                ## unwrapping should pop from the end (current expression) ##
                ## Note: bracket_index is relative to the current line length not soruce index ##
                line = line[:bracket_index] + "locals()['.internals']['.args'].pop()"
            else:
                try_set(depths.get(depth_total, None), -1, len(lines))
                lines += temp_lines
                line += temp_final_line
        ## unpacking ## - for operators
        else:
            ## variable ##
            if line.strip().isalnum() or named:
                final_line += line
            ## expression ##
            else:
                update = "locals()['.internals']['.args'].pop(0)"
                line = line.strip()
                if not is_item(line):
                    if line[0] in "({[": 
                        ## make sure the updating line has the bracket ##
                        update = line[0] + update
                        line = line[1:]
                    elif line[-1] in ")}]":
                        ## make sure the updating line has the bracket ##
                        update = update + line[-1]
                        line = line[:-1]
                    #  bracket_adjusted = True
                ## unpacking should pop from the start (since the line is in this order) ##
                final_line += update
                try_set(depths.get(depth_total, None), -1, len(lines))
                lines += unpack_adjust(line)
            line = ""
    if operator:
        final_line += " " + operator
    return line, lines, final_line, named, depths, fixed_lines


def is_item(source: str) -> bool:
    """
    Determines if the source is a valid item

    Note: we need to place the source inside
    a function in case of i.e. 'yield'
    """
    ## remove any key words it starts with ##
    source = source.lstrip()
    for keyword in ("return ", "yield ", "await ", "if ", "elif ", "while "):
        if source.startswith(keyword):
            source = source[len(keyword) :].lstrip()
    try:
        compile("def temp():" + source, "", "exec")
        return True
    except SyntaxError as e:
        # i.e. 
        # async def example():
        #     return (await 0)
        if "'await'" in e.msg:
            try:
                compile("async def temp():" + source, "", "exec")
                return True
            except SyntaxError:
                return False
        return False


def unpack(
    line: str = None,
    source_iter: Iterable = empty_generator(),
    source: str = "",
    unwrapping: bool = False,
    named: bool = False,
    index: int = 0,
    depth_total: int = 0,
    depths: dict = {},
    in_ternary_else: bool = False,
    fixed_lines: int = 0,
    signature: bool = False,
) -> tuple[list[str], str, int, int]:
    """
    Unpacks value yields from a line into a
    list of lines going towards its right side

    Note:
    depths = {index of the last depth, bracket, equals position, comma position, lines index}
    Note: lines indexes are relative to what lines are currently available e.g. the line variable
    """
    if line is None:
        line_iter = empty_generator()
    else:
        line_iter = enumerate(line, start=index - len(line) + 1)
    line_iter = chain(line_iter, source_iter)
    ## make sure 'space' == -1 for indentation ##
    (
        depth,
        end_index,
        space,
        lines,
        ID,
        line,
        final_line,
        prev,
        operator,
        bracket_index,
    ) = (0, 0, -1, [], "", "", "", (0, 0, ""), 0, None)
    indented = True
    if not unwrapping:
        indented = False
    for end_index, char in line_iter:
        ## record the source for string_collector_proxy (there might be better ways of doing this) ##
        ## collect strings and add to the lines ##
        if char == "'" or char == '"':
            temp_line, prev, temp_lines, temp_fixed_lines = string_collector_proxy(
                end_index, char, prev, line_iter, line, True
            )
            line += temp_line
            lines += temp_lines
            fixed_lines += temp_fixed_lines
        elif char == " ":
            line, space, indented = singly_space(end_index, char, line, space, indented)
            ## relies on the length of the line ##
            if depth_total in depths:
                depths[depth_total][0] -= 1
        ## dictionary assignment ##
        elif char == "[" and prev[-1] not in (" ", ""):
            line, lines, final_line, named, depths, fixed_lines = update_lines(
                line + char,
                lines,
                final_line,
                named,
                line_iter,
                source=source,
                index=end_index,
                depth_total=depth_total,
                depths=depths,
                fixed_lines=fixed_lines,
            )
        elif char == "\\":
            if space + 1 != end_index:
                line += " "
                space = end_index
            new_index = skip_line_continuation(line_iter, line, end_index)
            if depth_total in depths:
                depths[depth_total][0] = depths[depth_total][0] - new_index - end_index
        ## splitting operators ##
        elif char in ",=" or char in operators and is_item(line):
            if in_ternary_else:
                if char == "=" and source[end_index + 1 : end_index + 2] != "=":
                    try_set(depths.get(depth_total, None), 2, None)
                    line += char
                    break
                elif char == ",":
                    line += char
                    break

            flag = signature and char in ",="
            if flag:
                line += char
            ## since we can have i.e. ** or %= etc. ##
            if end_index - 1 != operator:
                if char == "=":
                    try_set(depths.get(depth_total, None), 2, None)
                ## for definitions ##
                if not flag:
                    line, lines, final_line, named, depths, fixed_lines = update_lines(
                        line,
                        lines,
                        final_line,
                        named,
                        operator=char,
                        source=source,
                        index=end_index,
                        depth_total=depth_total,
                        depths=depths,
                        fixed_lines=fixed_lines,
                    )
            else:
                key = {"=": 2, ",": 3}.get(char, None)
                try_set(depths.get(depth_total, None), key, len(line))
                if not flag:
                    final_line += char
            operator = end_index
        ## split and break condition ##
        elif depth == 0 and char in "#:;\n":
            if char == ":":
                line += ":"
            break
        elif char == "\n":
            fixed_lines += 1
        elif char == ":":  ## must be a named expression if depth is not zero ##
            line, lines, final_line, depths, fixed_lines = named_adjust(
                line,
                lines,
                final_line,
                line_iter,
                ID,
                source,
                end_index,
                depth_total,
                depths,
                fixed_lines,
            )
            named = False
            ## since we're going to skip some chars ##
            ID, prev = "", prev[:-1] + (char,)
            depth -= 1
            depths.pop(depth_total, None)
            depth_total -= 1
            continue
        else:
            ## record the current depth ##
            if char in "([{":
                depth_total += 1
                depths[depth] = [len(line), char, None, None, 0]
                if char == "(":
                    depth += 1
                    ## the index is in relation to the current line ##
                    bracket_index = len(line)
            elif char in ")}]":
                depths.pop(depth_total, None)
                depth_total -= 1
                if unwrapping and depth_total < 0 or char != inverse_bracket(depths.get(depth_total, (0, ""))[1]):
                    if not in_ternary_else:
                        line += char ## this is the bracket error likely
                    # print(unwrapping , depth_total < 0 , char != inverse_bracket(depths.get(depth_total, (0, ""))[1]))
                    if depth_total < 0:
                        break
                if char == ")":
                    depth -= 1
                    if depth == 0:
                        depths["in_definition"] = False
            ## check for unwrapping/updating ##
            if char.isalnum():
                ## in case of ... ... (otherwise you keep appending the ID) ##
                if space + 1 == end_index:
                    ID = ""
                ID += char
                if in_ternary_else and ID == "else":
                    line = line[:-3]
                    break
                (
                    adjusted,
                    line,
                    lines,
                    final_line,
                    named,
                    depth,
                    depth_total,
                    fixed_lines,
                ) = check_ID(
                    ID,
                    source_iter,
                    source,
                    line_iter,
                    source[end_index + 1 : end_index + 2],
                    end_index,
                    depths,
                    line,
                    lines,
                    final_line,
                    named,
                    bracket_index,
                    index,
                    depth,
                    depth_total,
                    fixed_lines,
                    in_ternary_else,
                )
                if adjusted:
                    ID, prev = "", prev[:-1] + (char,)
                    del adjusted
                    continue
            else:
                ID = ""
            line += char
            prev = prev[:-1] + (char,)
    if line:
        final_line += line
    if in_ternary_else:
        return lines, final_line, end_index, depths, depth_total, fixed_lines
    return lines, final_line, end_index, fixed_lines


def get_unpacked_lines(lines: str, reference: Union[int, None]) -> list[str]:
    """gets any lines that have been unpacked part of the ternary expression"""
    if reference == 0:
        return [], lines
    temp_lines = lines[reference:]
    lines = lines[:reference]
    return temp_lines, lines


def unpack_ternary(
    reference: int,
    source_iter: Iterable,
    source: str,
    named: bool,
    index: int,
    depth_total: int,
    depths: dict,
    fixed_lines: int,
) -> tuple[list[str], str, int, list[str], list[str]]:
    """unpacks the ternary expression and retrieves any new lines"""
    lines, final_line, end_index, depths, depth_total, fixed_lines = unpack(
        "",
        source_iter,
        source,
        False,
        named,
        index,
        depth_total,
        depths,
        True,
        fixed_lines=fixed_lines,
    )
    temp_lines, lines = get_unpacked_lines(lines, reference)
    return lines, end_index, final_line, temp_lines, depths, depth_total, fixed_lines


def clean_block(block: str) -> str:
    """removes any extra spaces and brackets"""
    block = block.strip()
    while block and block[-1] in ")]}":
        block = block[:-1]
    while block and block[0] in "([{":
        block = block[1:]
    return block


def check_ID(
    ID: str,
    source_iter: Iterable,
    source: str,
    line_iter: Iterable,
    next_char: str,
    end_index: int,
    depths: dict,
    line: str,
    lines: list[str],
    final_line: str,
    named: bool,
    bracket_index: int,
    index: int,
    depth: int = 0,
    depth_total: int = 0,
    fixed_lines: int = 0,
    in_ternary_else: bool = False,
) -> tuple[str, bool, bool]:
    """Checks the ID for updating the line"""
    adjusted = False
    if line.startswith("@"):
        final_line += "@" + ID
        for index, char in source_iter:
            final_line += char
            if char == "(":
                break
        line, adjusted = "", True
    if ID == "def" and next_char == " ":
        final_line += line + "f"
        for index, char in source_iter:
            final_line += char
            if char == "(":
                break
        line, adjusted = "", True
    elif ID == "lambda" and next_char in " :\\":
        line += "a"
        temp = collect_lambda(line, source_iter, source, (0, 0, ""), index)
        lines += temp[0]
        line = temp[1]
        fixed_lines += temp[2]
        adjusted = True
    ## unwrapping ##
    elif depth and ID == "yield" and next_char in " )]}\n;\\":
        ## what should happen when we unwrap? ##
        ## go from the last bracket onwards for the replacement ##
        line, lines, final_line, named, depths, fixed_lines = update_lines(
            line,
            lines,
            final_line,
            named,
            line_iter,
            bracket_index,
            yielding=True,
            source=source,
            index=end_index,
            depth_total=depth_total,
            depths=depths,
            fixed_lines=fixed_lines,
        )
        bracket_index = None
        ## since the unwrapping will accumulate up to the next bracket this ##
        ## will go unrecorded on this stack frame recieving but recorded and ##
        ## garbage collected on the recursed stack frame used on unwrapping ##
        depth -= 1
        depths.pop(depth_total, None)
        depth_total -= 1
        adjusted = True  ## to avoid: line += char (we include it in the final_line as the operator or in unwrapping)
    elif 1 < len(ID) < 4 and ID in ("and", "or", "is", "in"):
        line = line[: -len(ID)]
        line, lines, final_line, named, depths, fixed_lines = update_lines(
            line,
            lines,
            final_line,
            named,
            operator=ID,
            source=source,
            index=end_index,
            depth_total=depth_total,
            depths=depths,
            fixed_lines=fixed_lines,
        )
        adjusted = True
    ## I don't think you can have a value yield in a 'case' statement otherwise this too is in here ##
    elif next_char in " :\\" and 1 < len(ID) < 6 and ID in ("if", "elif", "while", "for"):
        ## i.e. ID='while' will have 'whil' but no 'e' since the char has not been added ##
        temp_line = line[: -len(ID) + 1]
        if ID == "if" and temp_line.lstrip():
            ## essentially, the final_line will be locals()['.internals']['.args'].pop(0 or None) ##
            ## and new lines will be added ##

            # 1. once you hit an if make sure the unpacking of it and itself
            ## comes before the last unpacking
            # 2. else statements just get added to the new lines

            ## Note: reason why the default is 0 is to ensure the ##
            ## lines are adjusted according to reference[-1] e.g. ##
            ## the current lines index at the depth of interest   ##
            reference = depths.get(depth_total, [0, " ", 0])
            if not in_ternary_else:
                depths["reference"] = len(lines)
                pop_forward = reference[1] in "({["
            reference = reference.pop()
            # print(reference,"|||||", len(line), index, end_index)
            # print(source[index:])
            # print(line)
            # print(final_line)
            # line = line[: -len(ID) + 1]
            if_block = temp_line

            ##############
            ## If block ##
            ##############

            ## line should be empty ##
            line = ""
            ## run it through unpack returning on ternary else ##
            ## then putting that current line as locals()['.internals']['.args'] ##
            if_block_lines, lines = get_unpacked_lines(lines, reference)
            (
                lines,
                end_index,
                if_condition,
                if_condition_lines,
                depths,
                depth_total,
                fixed_lines,
            ) = unpack_ternary(
                reference,
                source_iter,
                source,
                named,
                index,
                depth_total,
                depths,
                fixed_lines,
            )

            ################
            ## else block ##
            ################

            length = len(lines)
            ## then run it through unpack one more time to get the rest of the ternary else ##
            (
                lines,
                end_index,
                else_block,
                else_block_lines,
                depths,
                depth_total,
                fixed_lines,
            ) = unpack_ternary(
                reference,
                source_iter,
                source,
                named,
                end_index,
                depth_total,
                depths,
                fixed_lines,
            )
            if else_block:
                if else_block[-1] in ",=":
                    depths["char"] = else_block[-1]
                    else_block = else_block[:-1]
                depths["else_block"] = else_block
            ## add all the lines ##
            if_block = ["    " + clean_block(if_block)]
            else_block = ["    " + clean_block(else_block)]
            diff = len(lines) - length
            replace = False
            if diff:
                if else_block[0].isspace():
                    temp_index = depths.pop("diff")
                    ## the entire block is the else_block ##
                    if temp_index[1] is None:
                        else_block = indent_lines(lines[temp_index[0] :])
                        lines = lines[: temp_index[0]]
                    ## the if block is the else block ##
                    else:
                        replace = True
                        else_block = indent_lines(
                            lines[temp_index[0] : temp_index[1]],
                            -4 * (temp_index[2] - 1),
                        )
                else:
                    else_block = indent_lines(lines[reference:diff])
                    lines = lines[:reference]
            new_lines = (
                if_condition_lines
                + ["if " + if_condition + ":"]
                + indent_lines(if_block_lines)  ## just extract this ##
                + if_block
                + ["else:"]
                + indent_lines(else_block_lines)
                + else_block
            )
            ## if missing an else block it'll be in the previous if_block otherwise the prevous ##
            ## ternary expression is the else block, we get indicated whether or not there was a ##
            ## previous if block incomplete by the frame before ##
            if replace:
                # print("-----------------------------")
                # print(new_lines)
                # print(lines[temp_index[0]: temp_index[1]])
                # print("-----------------------------")
                lines[temp_index[0] : temp_index[1]] = indent_lines(new_lines, 4 * temp_index[2])
            else:
                lines += new_lines
            check = if_block[0:1]
            ## depth > 0 should also work e.g. depths in further blocks should be < 0 ##
            if (replace == False or depths.get("depth", depth) >= depth) and not (
                check and check[0].lstrip().startswith("if ")
            ):
                base = length + len(if_condition_lines) + 1
                ## because it's replaced we need to ensure it's adjusted correctly ##
                indent = 1
                if replace:
                    base += temp_index[0]
                    indent += get_indent(check[0]) // 4
                depths["diff"] = (base, base + len(if_block_lines + if_block), indent)
                depths["depth"] = depth
            else:
                # print("DEPTH:", depth, depths["depth"])
                # print(check[0], "----------------------")
                depths["diff"] = (length, None)
            if not in_ternary_else:
                if pop_forward:
                    final_line += "locals()['.internals']['.args'].pop(0)"
                else:
                    final_line += "locals()['.internals']['.args'].pop()"
                reference = depths.pop("reference")
                char, else_block = depths.pop("char", ""), depths.pop("else_block", "")
                if depth == 0:
                    else_block = ""
                lines[reference:] = ternary_adjust(lines[reference:])
                final_line += char + else_block
        else:
            final_line += ID + " "
            line = temp_line
        adjusted = True
    return adjusted, line, lines, final_line, named, depth, depth_total, fixed_lines


def ternary_adjust(lines: list[str]) -> list[str]:
    def check(line: str) -> bool:
        try:
            temp_line = line[0].strip()
        except:
            return True
        return temp_line.startswith("if ") or temp_line.startswith("else ") or temp_line.startswith("else:")

    line_iter = enumerate(lines)
    for index, line in line_iter:
        if check(line) == False and check(lines[index + 1 : index + 2]):
            lines[index] = " " * get_indent(line) + "locals()['.internals']['.args'] += [%s]" % line.strip()
            next(line_iter, None)
    return lines


def collect_definition(self, start_index: int, reference_indent: int) -> None:
    """
    Collects a block of code from source, specifically a
    definition block in the case of this modules use case
    """
    name, args = get_signature(self.line, True)
    if args:
        lines, line, _, fixed_lines = unpack("", enumerate(args), args, signature=True)
        self.lines += lines + [" " * get_indent(self.line) + "def " + name + "(%s):" % line]
        self.fixed_lines += fixed_lines
        start_index = len(self.line) + 1

    def skip_line(self, start_index: int) -> tuple[int, int]:
        ## we're not specific about formatting the definitions ##
        ## we just need to make sure to include them ##
        prev = (0, 0, "")
        for self.index, self.char in self.source_iter:
            if self.char == "'" or self.char == '"':
                _, prev, _, fixed_lines = string_collector_proxy(
                    self.index,
                    self.char,
                    prev,
                    self.source_iter,
                    self.line,
                    self.source,
                )
                self.lineno += fixed_lines
            ## newline ##
            elif self.char == "\n":
                break
        ## add the line and get the indentation to check if continuing ##
        self.lineno += 1
        self.lines += [self.source[start_index : self.index]]
        indent = get_indent(self.source[self.index + 1 :])
        start_index = self.index + 1
        return indent, start_index

    if self.source[self.index] != "\n":
        indent, start_index = skip_line(self, start_index)
    indent = reference_indent + 1
    while reference_indent < indent:
        indent, start_index = skip_line(self, start_index)
    if self.char != "\n":
        self.lines[-1] += self.char


## Note: line.startswith("except") will need to put a try statement in front (if it's not there e.g. is less than the minimum indent) ##
## match case default was introduced in python 3.10


def is_alternative_statement(line: str) -> bool:
    """Checks if a line is an alternative statement"""
    return (line.startswith("elif") or line.startswith("else") or line.startswith("case") and line[4] in " :") or (
        line.startswith("default") and line[7] in " :"
    )


def is_loop(line: str) -> bool:
    """Checks if a line is a loop"""
    if line.startswith("async "):
        line = line[5:]
        return line[get_indent(line) :].startswith("for ")
    return line.startswith("for ") or line.startswith("while ")


def is_definition(line: str) -> bool:
    """Checks if a line is a definition"""
    if line.startswith("async "):
        line = line[5:]
        return line[get_indent(line) :].startswith("def ")
    return line.startswith("def ") or line.startswith("class ")


########################
### code adjustments ###
########################
def skip_alternative_statements(
    line_iter: Iterable,
    current_min: int,
    check: FunctionType = is_alternative_statement,
) -> tuple[int, str, int]:
    """Skips all alternative statements for the control flow adjustment"""
    adjuster = 0
    for index, line in line_iter:
        temp_indent = get_indent(line)
        temp_line = line[temp_indent:]
        if temp_indent <= current_min and not check(temp_line):
            ## to avoid skipping the non alternative statement ##
            adjuster = 1
            break

    return index, adjuster, line, temp_indent


def skip_alt_stmnt_proxy(
    line_iter: Iterable,
    temp_indent: int,
    indexes: list[int],
    index: int,
    shift: int,
    append_shift: int,
    **kwargs,
) -> tuple[list[int], int, str, bool, int]:
    """skips alternative statments and updates the linetable"""
    breaking = False
    end_index, adjuster, line, temp_indent = skip_alternative_statements(
        line_iter,
        temp_indent,
        **kwargs,
    )
    ## remove from the linetable and update the index ##
    del indexes[index + append_shift - shift : end_index + 1 + append_shift - adjuster - shift]
    if not indexes:
        line = ""
    shift += end_index + 1 - adjuster - index
    if adjuster == 0:
        breaking = True
    index = end_index
    return indexes, index, line, breaking, shift


def statement_adjust(
    temp_line: str,
    line_iter: Iterable,
    new_lines: list[str],
    indexes: list[int],
    index: int,
    line: str,
    temp_indent: int,
    shift: int,
    append_shift: int,
    except_adjust: int,
) -> tuple[list[str], list[int], int, str, bool]:
    """Adjusts the current statement for control_flow_adjust"""
    breaking = False
    condition = (temp_line.startswith("except") and temp_line[6] in " :"), (
        temp_line.startswith("finally") and temp_line[7] in " :"
    )
    if condition[0] or condition[1]:
        ## temp_line gets added after ##
        if not new_lines:
            new_lines = [" " * 4 + "try:", " " * 8 + "pass"]
            indexes = [indexes[0], indexes[0]] + indexes
            append_shift += 2
        else:
            new_lines = [" " * 4 + "try:"] + indent_lines(new_lines)
            ## add to the linetable ##
            indexes = [indexes[0]] + indexes
            append_shift += 1
        if except_adjust is None:
            if condition[1]:
                except_adjust = -1
            else:
                except_adjust = temp_indent
    elif is_alternative_statement(temp_line):
        indexes, index, line, breaking, shift = skip_alt_stmnt_proxy(
            line_iter, temp_indent, indexes, index, shift, append_shift
        )
    return new_lines, indexes, index, line, breaking, shift, append_shift, except_adjust


def control_flow_adjust(lines: list[str], indexes: list[int], reference_indent: int = 4) -> tuple[list[str], list[int]]:
    """
    removes unreachable control flow blocks that
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an
    indentation of 4 (4 because we're in a function)

    It will also add 'try:' when there's an 'except'
    or 'finally' line on the next minimum indent
    """
    new_lines, current_min, line_iter, shift, append_shift = (
        [],
        get_indent(lines[0]),
        enumerate(lines),
        0,
        0,
    )
    ## check if the first line is an alternative statement ##
    index, line = next(line_iter)
    temp_indent = get_indent(line)
    new_lines, indexes, index, line, breaking, shift, append_shift, except_adjust = statement_adjust(
        line[temp_indent:],
        line_iter,
        new_lines,
        indexes,
        index,
        line,
        temp_indent,
        shift,
        append_shift,
        None,
    )
    ## add the line (adjust if indentation is not reference_indent) ##
    if current_min != reference_indent:
        ## adjust using the current_min until it's the same as reference_indent ##
        new_lines += [line[current_min - 4 :]]
    else:
        return (
            new_lines + indent_lines(lines[index:], 4 - reference_indent),
            indexes,
        )
    if not breaking:
        for index, line in line_iter:
            temp_indent = get_indent(line)
            temp_line = line[temp_indent:]
            if temp_indent < current_min:
                current_min = temp_indent
                (
                    new_lines,
                    indexes,
                    index,
                    line,
                    breaking,
                    shift,
                    append_shift,
                    except_adjust,
                ) = statement_adjust(
                    temp_line,
                    line_iter,
                    new_lines,
                    indexes,
                    index,
                    line,
                    temp_indent,
                    shift,
                    append_shift,
                    except_adjust,
                )
                if breaking:
                    break
            elif temp_indent == except_adjust and temp_line.startswith("except") and temp_line[6] in " :":
                except_adjust = -1  ## so long as it's not x % 4 == 0 or None ##
                indexes, index, line, breaking, shift = skip_alt_stmnt_proxy(
                    line_iter,
                    temp_indent,
                    indexes,
                    index,
                    shift,
                    append_shift,
                    check=lambda line: line.startswith("except") and line[6] in " :",
                )
            ## add the line (adjust if indentation is not reference_indent) ##
            if current_min != reference_indent:
                except_adjust = -1
                ## adjust using the current_min until it's the same as reference_indent ##
                new_lines += [line[current_min - 4 :]]
            else:
                return (
                    new_lines + indent_lines(lines[index:], 4 - reference_indent),
                    indexes,
                )
    return new_lines, indexes


def indent_lines(lines: list[str], indent: int = 4) -> list[str]:
    """indents a list of strings acting as lines"""
    if indent > 0:
        return [" " * indent + line for line in lines]
    if indent < 0:
        indent = -indent
        return [line[indent:] for line in lines]
    return lines


def iter_adjust(line: str, number_of_indents: int) -> str:
    """
    Replaces the iterator of a for loop
    with an adjusted version (for tracking iterators)

    e.g. we extract the second ... in:
    for ... in ...:

    While loops get adjusted on custom adjustment
    """
    temp_line = line[number_of_indents:]
    index, depth, ID, line_iter = (
        0,
        0,
        "",
        enumerate(temp_line, number_of_indents),
    )
    for index, char in line_iter:
        ## the 'in' key word must be avoided in all forms of loop comprehension ##
        depth = update_depth(depth, char, ("([{", ")]}"))
        if char.isalnum() and depth == 0:
            ID += char
            if ID == "in":
                if next(line_iter)[1] == " ":
                    break
                ID = ""
        else:
            ID = ""
    ## adjust by 2 to skip the 'n' and ' ' in 'in ' that would've been deduced ##
    index += 2
    iterator = line[index:-1]  ## -1 to remove the end colon ##
    ## remove the leading and trailing whitespace and then it should be a variable name ##
    if iterator.strip().isalnum():
        return line
    return line[:index] + "locals()['.internals']['.%s']:" % number_of_indents


def is_statement(line: str, statement: str) -> bool:
    """To make sure the line is a statement with more accuracy and efficiency"""
    ## check that they're the same ##
    for index, (char1, char2) in enumerate(zip(line, statement)):
        if char1 != char2:
            break
    index += 1
    if index != len(statement):
        return False
    ## check it's not a variable ##
    line = line[index:]
    if line:
        if line[0] in " ;\n":
            return True
        return False
    return True


def skip_blocks(new_lines: list[str], line_iter: Iterable, index: int, line: str) -> tuple[list[str], str, int]:
    """
    Skips over for/while, definition blocks,
    and removes indentation from the line
    """
    indent = get_indent(line)
    temp_line = line[indent:]
    check = lambda temp_line: is_loop(temp_line) or is_definition(temp_line)
    if check(temp_line):
        while check(temp_line):
            new_lines += [line[indent:]]
            temp_indent = None
            for index, line in line_iter:
                temp_indent = get_indent(line)
                if temp_indent <= indent:
                    break
                new_lines += [line[indent:]]
            ## continue back ##
            indent = temp_indent
            temp_line = line[indent:]
        return new_lines, None, None
    return new_lines, temp_line, index


def loop_adjust(
    lines: list[str], indexes: list[int], outer_loop: list[str], *pos: tuple[int, int]
) -> tuple[list[str], list[int]]:
    """
    Formats the current code block
    being executed such that all the
    continue -> break;
    break -> empty the current iter; break;

    This allows us to use the control
    flow statements by implementing a
    simple for loop and if statement
    to finish the current loop
    """
    ## flag determines if we need to complete a sliced loop or simply dedent its complete form ##
    new_lines, flag, line_iter = [], False, enumerate(lines)
    for index, line in line_iter:
        ## skip over for/while and definition blocks ##
        ## since these are complete blocks of their own ##
        ## and don't need to be adjusted ##
        new_lines, temp_line, index = skip_blocks(new_lines, line_iter, index, line)
        if index is None:
            continue
        ## adjustments ##
        if is_statement(temp_line, "continue"):
            flag = True
            new_lines += ["break"]
        elif is_statement(temp_line, "break"):
            flag = True
            new_lines += ["locals()['.internals']['.continue']=False", "break"]
            ## the index can be None since the line should run without errors ##
            indexes = indexes[:index] + [None] + indexes[index:]
        else:
            new_lines += [temp_line]
    ## adjust the outer loops iterator in case it's an iterator that needs its tracked version ##
    temp_line = outer_loop[0]
    number_of_indents = get_indent(temp_line)
    if temp_line[number_of_indents:].startswith("for "):
        outer_loop[0] = iter_adjust(temp_line, number_of_indents)
    if flag:
        ## the loop adjust itself ##
        return [
            "    locals()['.internals']['.continue']=True",
            "    for _ in (None,):",
        ] + indent_lines(new_lines, 8 - get_indent(new_lines[0])) + [
            "    if locals()['.internals']['.continue']:"
            ## add the outer loop (dedented so that it works) ##
        ] + indent_lines(
            outer_loop, 8 - get_indent(outer_loop[0])
        ), [
            ## add all the indexes which are also adjusted for the changes ##
            None,
            None,
        ] + indexes + [
            None,
        ] + list(
            range(*pos)
        )
    ## If it doesn't need any adjustments e.g. continue and break statements ##
    ## then we just dedent the current lines and add the outer loop ##
    return indent_lines(lines, 4 - get_indent(lines[0])) + indent_lines(
        outer_loop, 4 - get_indent(outer_loop[0])
    ), indexes + list(range(*pos))


def yield_adjust(temp_line: str, indent: str) -> list[str]:
    """
    temp_line: line trimmed at the start by its indent
    indent: the current indent in string form
    """
    if temp_line[:6] == "yield " and temp_line[5:].lstrip().startswith("from "):
        return [
            ## 11 to get past the yield from
            indent
            + "locals()['.internals']['.%s']=locals()['.internals']['.yieldfrom']=iter(%s)"
            % (len(indent), temp_line[11:]),
            indent + "for locals()['.internals']['.i'] in locals()['.internals']['.yieldfrom']:",
            indent + "    return locals()['.internals']['.i']",
            indent + "    if locals()['.internals']['.send']:",
            indent + "        return locals()['.internals']['.yieldfrom'].send(locals()['.internals']['.send'])",
        ]
    if temp_line.startswith("yield ") or temp_line.startswith("yield)") or temp_line == "yield":
        return [indent + "return" + temp_line[5:]]  ## 5 to retain the whitespace ##


def get_loops(lineno: int, jump_positions: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    returns a list of tuples (start_lineno,end_lineno) for the loop
    positions in the source code that encapsulate the current lineno
    """
    ## get the outer loops that contian the current lineno ##
    loops = []
    ## jump_positions are in the form (start_lineno,end_lineno) ##
    for pos in jump_positions:

        ## importantly we go from start to finish to capture nesting loops ##
        ## make sure the lineno is contained within the position for a ##
        ## loop adjustment and because the jump positions are ordered we ##
        ## can also break when the start lineno is beyond the current lineno ##
        if lineno <= pos[0]:
            break
        if lineno <= pos[1]:
            ## subtract 1 for 0 based indexing; it's only got one specific ##
            ## use case that requires it to be an array accessor ##
            loops += [(pos[0] - 1, pos[1] - 1)]
    return loops


def extract_source_from_comparison(
    code_obj: CodeType,
    source: str,
    extractor: FunctionType,
    globals: dict = None,
    locals: dict = None,
    mode: str = "eval",
    strictness: int = 1,
) -> str:
    """
    Extracts source via a comparison of
    extracted source codes code object
    and the current code object

    mode: 
        "eval" or "exec" is generally for expression or functions respectively
    strictness:
        should be a positive integer determining how strict the code comparison 
        needs to be in order to pass i.e. higher number means more strict/precise
        source code.

        Currently the highest level of strictness is 2

        If strictness is set to a number greater the highest current strictness
        or a negative value no source code will be compared, and if the strictness
        is set to 0 then it's the first source code extraction to make it to the 
        comparison that will pass.
    """
    if type(strictness) != int or strictness < 1:
        raise ValueError("strictness must be a positive integer")
    if strictness < 3:
        if strictness == 0:
            import warnings
            warnings.warn("strictness 0 Is not recommended (see docstring)", category=UserWarning)
        attrs = (
            "co_freevars",
            "co_cellvars",
            "co_nlocals",
            "co_stacksize",
            "co_code",
            "co_consts",
            "co_names",
            "co_varnames",
            "co_name",
        )
        executor = eval
        if mode == "exec":

            def exec_proxy(name: str, source: str, globals: dict, locals: dict):
                exec(source, globals, locals)
                temp_locals = currentframe().f_locals
                ## if it's not in current frame then it's allocated in locals ##
                return temp_locals.get(name, locals.get(name, None))

            executor = partial(exec_proxy, code_obj.co_name)
        if isinstance(source, list):
            source = "".join(source)
        extracing_genexpr = getcode(extractor).co_name == "extract_genexpr"
        for col_offset, end_col_offset in extractor(source):
            try:  ## we need to make it a try-except in case of potential syntax errors towards the end of the line/s ##
                ## eval should be safe here assuming we have correctly extracted the expression - we can't use compile because it gives a different result ##
                temp_source = source[col_offset:end_col_offset]
                ## trim off leading newlines ##
                while temp_source[0] == "\n":
                    temp_source = temp_source[1:]
                indent = get_indent(temp_source)
                ## make sure to the source is not indented (otherwise comparison will fail) ##
                if indent:
                    lines = [line for line in temp_source.split("\n") if not line.isspace()]
                    temp_source = "\n".join(indent_lines(lines, -indent))
                # print(repr(temp_source))
                # print("---------------------------------")
                temp_code = compile(temp_source, "<Don't track>", mode) ## very important, because track_iter otherwise will interfere with the comparison ##
                try:
                    generator = executor(temp_code, globals, locals)
                except NameError as e:
                    if not extracing_genexpr:
                        raise e
                    ## NameError since genexpr's first iterator is stored as .0 ##
                    name = e.args[0].split("'")[1]
                    temp_locals = locals 
                    temp_locals.update({name: locals[".0"]})
                    generator = executor(temp_code, globals, temp_locals)
                try:
                    temp_code = getcode(generator)
                    if temp_code.co_name != code_obj.co_name:
                        continue
                except AttributeError:
                    continue
                ## attr_cmp should get most simple cases, code_cmp should cover nonlocal + closures ideally ##
                ## Note: the comparison should be as strict or better than the strictness ##
                if attr_cmp(temp_code, code_obj, attrs) + code_cmp(temp_code, code_obj) >= strictness:
                    return temp_source
            except SyntaxError as e:
                pass
    raise Exception("No matches to the original source code found")


def expr_getsource(FUNC: Union[FunctionType, GeneratorType]) -> str:
    """
    Uses the source code extracting expressions until a
    match is found on a code object basis to get the source

    You can also to some extent use co_positions as well

    Note:
    the extractor should return a string and if using a
    lambda extractor it will take in a string input but
    if using a generator expression extractor it will
    take a list instead
    """
    code_obj = getcode(FUNC)
    name = code_obj.co_name
    mode = "eval"
    if name == "<lambda>":
        ## here source is a : str
        if is_cli():
            source = cli_findsource()
        else:
            source = getsource(code_obj)
        extractor = extract_lambda
        ## functions don't need their variables defined right away ##

        if isinstance(FUNC, FunctionType):
            globals = FUNC.__globals__
            locals = get_nonlocals(FUNC)
        else:
            frame = getframe(FUNC)
            globals = frame.f_globals
            locals = frame.f_locals
    elif name == "<genexpr>":
        frame = getframe(FUNC)
        ## here source is a : list[str]
        if is_cli():
            source = cli_findsource()
        else:
            lineno = frame.f_lineno - 1
            source = findsource(code_obj)[0][lineno:]
        extractor = extract_genexpr
        globals = frame.f_globals
        locals = frame.f_locals
    ## function generators ##
    elif name.isidentifier():
        if is_cli():
            source = cli_findsource()
        else:
            lineno = code_obj.co_firstlineno - 1
            source = findsource(code_obj)[0][lineno:]
        extractor = extract_function
        ## get the globals and locals whether it's initialized or not ##
        if isinstance(FUNC, FunctionType):
            globals = FUNC.__globals__
            locals = get_nonlocals(FUNC)
        else:
            frame = getframe(FUNC)
            ## Note: since the frame is not initialized yet we can't get the locals ##
            ## but nonlocals are locals so we can get these ##
            globals = frame.f_globals
            locals = frame.f_locals
        mode = "exec"
    else:
        raise TypeError("Unexpected object does not have a source extractor")
    return extract_source_from_comparison(code_obj, source, extractor, globals, locals, mode)


def extract_genexpr(
    source: str,
    recursion: bool = False,
    depths: dict = {},
    genexpr_depth: Union[int, None] = None,
) -> GeneratorType:
    """Extracts each generator expression from a list of the source code lines"""
    ID, depth, prev = (
        "",
        0,
        (0, 0, ""),
    )
    source_iter = enumerate(source)
    for index, char in source_iter:
        ## skip all strings if not in genexpr
        if char == "'" or char == '"':
            _, prev, _ = string_collector_proxy(index, char, prev, source_iter)
        elif ID == "for" and char in " \\":
            if genexpr_depth and depth > genexpr_depth:
                temp_source = source[temp_col_offset:]
                for offsets in extract_genexpr(temp_source, True, depths, genexpr_depth):
                    yield temp_col_offset + offsets[0], temp_col_offset + offsets[1]
            else:
                genexpr_depth, col_offset = depth, depths[depth]
            ID = ""
        ## detect brackets
        elif char == "(":
            depth += 1
            depths[depth] = index
            temp_col_offset = index
        elif char == ")":
            depths.pop(depth, None)
            if depth == genexpr_depth:
                yield col_offset, index + 1
                if recursion:
                    return
                genexpr_depth = None
            depth -= 1
        if depth:
            ## record ID ##
            if char.isalnum():
                ID += char
            else:
                ID = ""


def extract_lambda(source_code: str, recursion: bool = False) -> GeneratorType:
    """Extracts each lambda expression from the source code string"""
    ID, lambda_depth, depth, prev = "", None, 0, (0, 0, "")
    source_iter = enumerate(source_code)
    for index, char in source_iter:
        ## skip all strings (we only want the offsets)
        if char == "'" or char == '"':
            _, prev, _ = string_collector_proxy(index, char, prev, source_iter)
        elif lambda_depth is not None and (char in "\n;," or depth + 1 == lambda_depth):
            # lambda_depth needed in case of brackets; depth + 1 since depth would've got reduced by 1
            yield col_offset, index
            if recursion:
                return
            ## clear the ID since the next index could be the start of a lambda
            ID, lambda_depth = "", None
        elif char in " \\:" and ID == "lambda":
            if lambda_depth is not None:
                temp_source = source_code[index - 6 :]
                for offsets in extract_lambda(temp_source, recursion=True):
                    yield index - 6 + offsets[0], index - 6 + offsets[1]
            else:
                lambda_depth, col_offset = depth, index - 6
            ID = ""
        ## needs to be skipped this way in case of '\n' (since this is considered an end col_offset)
        elif char == "\\":
            skip_line_continuation(source_iter, source_code, index)
        ## detect brackets (lambda can be in all 3 types of brackets) ##
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char.isalnum():
            ID += char
        else:
            ID = ""
    ## in case of a current match ending ##
    if lambda_depth is not None:
        yield col_offset, None


def except_adjust(current_lines: list[str], exception_lines: list[str], final_line: str) -> list[str]:
    """
    Checks if lines that were adjusted because of value yields
    were in an except statement and therefore needs adjusting
    """
    ## except statement with its adjustments ##
    indent = " " * 4
    reference_indent = get_indent(final_line)
    index = 0
    for index, line in enumerate(current_lines[::-1], start=1):
        current_lines[-index] = indent + current_lines[-index]
        reference_indent = get_indent(line)
        if line[reference_indent:].startswith("try"):
            break
    number_of_indents = reference_indent + 8
    current_indent = " " * number_of_indents
    # print(current_lines, exception_lines)
    return (
        # [" " * reference_indent + "try:"]
        current_lines[:-index]
        + [" " * reference_indent + "try:"]
        + current_lines[-index:]
        + [
            current_indent[:-4] + "except:",
            current_indent + "locals()['.internals']['.error'] = locals()['.internals']['.exc_info']()[1]",
        ]
        # + indent_lines(exception_lines, number_of_indents)
        + except_catch_adjust(final_line, exception_lines)
    ), reference_indent


def extract_as(line: str) -> tuple[str, str]:
    """splits a line by its 'as' keyword"""
    line_iter, prev, ID = enumerate(line), (0, 0, ""), ""
    for index, char in line_iter:
        if char == "'" or char == '"':
            _, prev, _ = string_collector_proxy(
                index,
                char,
                prev,
                line_iter,
            )
        if char.isalnum():
            ID += char
        else:
            if char == " " and ID == "as":
                return line[: index - 3], line[index:]
            ID = ""
    return line, ""


def except_catch_adjust(line: str, lines: list[str]) -> list[str]:
    """
    adjusts the lines for the except statement
    
    Expects:
    line = except ... : ...
    """
    indent = get_indent(line)
    ## length of except is 6, -1 to remove the end colon ##
    line = line[indent + 6 : -1]
    ## extract the 'as' keyword position ##
    line, as_keyword = extract_as(line)
    if as_keyword:
        as_keyword = [" " * (indent + 8) + as_keyword + " = locals()['.internals']['.error']"]
    else:
        as_keyword = []
    return (
        indent_lines(lines, indent + 4)
        + [
            " " * (indent + 4) + "if isinstance(locals()['.internals']['.error'], " + line + "):",
            " " * (indent + 8) + "locals()['.continue_error'] = False",
            # " " * (indent + 4) + "else:",
            # " " * (indent + 8),
        ]
        + as_keyword
    )


def singly_space(index: int, char: str, line: str, space: int, indented: bool) -> tuple[str, int, int]:
    """For ensuring all spaces in a line are single spaces"""
    if indented:
        if space + 1 != index:
            line += char
    else:
        line += char
        if space + 1 != index:
            indented = 1
    return line, index, indented


def outer_loop_adjust(
    blocks: list[str],
    indexes: list[int],
    source_lines: list[str],
    loops: list[tuple[int, int]],
    end_pos: int,  ## in case no loops
) -> tuple[list[str], list[int]]:
    """Adds all the outer loops with the iterable adjusted to the current block and its indexes"""
    ## add all the outer loops ##
    for start_pos, end_pos in loops[::-1]:
        end_pos += 1  ## since the jump_positions are inclusion based ##
        block = source_lines[start_pos:end_pos]
        if block:
            temp_line = block[0]
            number_of_indents = get_indent(temp_line)
            if temp_line[number_of_indents:].startswith("for "):
                block[0] = iter_adjust(temp_line, number_of_indents)
        blocks += indent_lines(block, 4 - number_of_indents)
        ## we need to add 1 to the end position since it's 0 based ( e.g. to be inclusive) ##
        indexes += list(range(start_pos, end_pos))
    return blocks + source_lines[end_pos:], indexes


def setup_next_line(self, char: str = " ", indentation: int = None) -> None:
    """sets up the next line with indentation or not"""
    if char in ":;":
        ## assumes the current line is i.e. ; ... ; ... or if ... : ... ; ... ##
        ## if it's not this then we should get an empty line and this assumption ##
        ## will not take effect in modifying lines ##
        self.line, self.indented = " " * indentation, True
        return
    self.line, self.indented = "", False


def unpack_lambda(source: str) -> list[str]:
    """Unpacks the lambda into a single source line"""
    depth = 0
    for index, char in enumerate(source):
        if char == ":" and depth == 0:
            return [source[index + 1 :]]
        depth = update_depth(depth, char, ("([{", ")]}"))
    raise SyntaxError("Unexpected format encountered")


def get_signature(line: str, args: bool = False) -> Union[str, tuple[str, str]]:
    """Returns the function signature and its arguments if desired"""
    ID, has_definition, has_args = "", False, False
    for index, char in enumerate(line):
        if char == "(":
            has_args = True
            break
        if char.isalnum():
            ID += char
            if not has_definition and ID == "def":
                ID, has_definition = "", True
        else:
            ID = ""
    if args:
        args = ""
        if has_args:
            ## -1 rstrip() -1 since you can have i.e. func( ... ) :
            args = line[index + 1 :].strip()[:-1].rstrip()[:-1]
        return ID, args
    return ID


def collect_lambda(
    line: str,
    source_iter: Iterable,
    source: str,
    prev: tuple[int, int, str],
    index: int,
) -> tuple[str, str]:
    """
    Collects a lambda function into a single line
    
    Expects line to be 'lambda ...'
    """
    depth, in_definition = 0, False
    lines, line, index, fixed_lines = unpack(line, source_iter, source, index=index, signature=True)
    char = source[index]
    for index, char in source_iter:
        if char == "'" or char == '"':
            string_collected, prev, adjustments, temp = string_collector_proxy(
                index,
                char,
                prev,
                source_iter,
                line,
                source,
            )
            line += string_collected
            fixed_lines += temp
        elif char in "#\n;" or (char == ":" and source[index + 1 : index + 2] != "=") and in_definition:
            break
        else:
            if not in_definition and char == ":":
                in_definition = True
            else:
                depth = update_depth(depth, char, ("([{", ")]}"))
                if depth == -1:
                    break
            line += char
    return lines, line, fixed_lines, char


def sign(
    FUNC: FunctionType,
    FUNC2: FunctionType,
    globals: dict = None,
    boundmethod: bool = False,
    closure: tuple[CellType] = None,
) -> FunctionType:
    """signs a function with the signature of another function"""
    annotations = FUNC2.__annotations__
    # temporarily remove the annotations from the signature to avoid scope issues
    FUNC2.__annotations__ = {}
    _signature = format(signature(FUNC2))
    FUNC2.__annotations__ = annotations
    if boundmethod:
        _signature = "(self, " + _signature[1:]
    _signature = FUNC2.__name__ + _signature + ":"
    source = skip_source_definition(getsource(FUNC))
    ## create the function ##
    source = "def %s%s" % (_signature, source)
    exec(source, globals, locals(), closure=closure)
    temp = locals()[FUNC2.__name__]
    temp.__source__ = source
    temp.__doc__ = FUNC2.__doc__
    temp.__annotations__ = annotations
    return temp


######################################################
#### Cleaning and adjusting Generator source code ####
######################################################


def record_jumps(self: object, number_of_indents: int) -> None:
    """Records the jump positions for the loops (for and while) to help with code adjustments"""
    ## has to be a list since we're assigning ##
    self.jump_positions += [[self.lineno, None]]
    self.jump_stack += [(number_of_indents, len(self.jump_positions) - 1)]


def custom_adjustment(self: object, line: str, number_of_indents: int = 0) -> list[str]:
    """
    It does the following to the source lines:

    1. replace all lines that start with yields with returns to start with
    2. make sure the generator is closed on regular returns
    3. save the iterator from the for loops replacing with a nonlocal variation
    4. tend to all yield from ... with the same for loop variation
    5. adjust all value yields either via unwrapping or unpacking
    """
    temp_line = line[number_of_indents:]
    indent = " " * number_of_indents
    ## decorator ##
    if temp_line.startswith("@"):
        self.decorator = True
        return [line]
    ## yield ##
    result = yield_adjust(temp_line, indent)
    if temp_line.startswith("yield from "):
        lineno = self.lineno
        self.lineno += len(result) - 1
        ## lineno + 1 it starts after this line ##
        ## and lineno + len(result) - 1 to include the full loops block subtract the current line ##
        self.jump_positions += [[lineno + 1, self.lineno]]
    if result is not None:
        return result
    ## loops ##
    if is_loop(temp_line):
        record_jumps(self, number_of_indents)
        return [line]
    ## return ##
    if temp_line == "return" or temp_line.startswith("return "):
        ## close the generator then return ##
        ## have to use a try-finally in case the user returns a value from locals() ##
        return [indent + "return EOF('" + temp_line[7:] + "')"]
    ## nonlocal ##
    if temp_line.startswith("nonlocal "):
        ## we have to remove the nonlocal keyword since there will be no bindings. ##
        ## The args are collected in __init__ for unintialized function generators; ##
        ## initialized generators already have them in their locals ##
        self.lineno -= 1
        return []
    return [line]


def update_jump_positions(self: object, reference_indent: int = -1) -> list[str]:
    """
    Updates the end jump positions in self._internals["jump_positions"].
    It may also append the current lines with adjustments if it's a while
    loop that used a value yield in its condition
    """
    if self.jump_stack:
        end_lineno = self.lineno
        while self.jump_stack and reference_indent <= self.jump_stack[-1][0]:  # -1: top of stack, 0: indent
            index = self.jump_stack.pop()[1]
            self.jump_positions[index][1] = end_lineno
            ## add the adjustments


def append_line(
    self: object,
    running: bool,
) -> None:
    """skips comments, adds definitions, appends the line, updates the indentation, and updates the jump positions"""
    ## skip comments ##
    if self.char == "#":
        for self.index, self.char in self.source_iter:
            if self.char == "\n":
                break
    ## make sure to include it ##
    if self.char == ":":
        self.indentation = get_indent(self.line) + 4  # in case of ';'
        self.line += self.char
    if self.line and not self.line.isspace():  ## empty lines are possible ##
        reference_indent = get_indent(self.line)
        ## make sure the line is corrected if it currently assumes indentation when it shouldn't ##
        if self.indent_adjust and reference_indent - (self.char == ":") * 4 >= self.indentation - self.indent_adjust:
            self.line = " " * self.indent_adjust + self.line
        else:
            self.indent_adjust = 0
        update_jump_positions(self, reference_indent)
        ## skip the definitions ##
        temp_line = self.line[reference_indent:]
        if is_definition(temp_line):
            collect_definition(
                self,
                self.index - len(self.line) + 1,
                reference_indent,
            )
            if self.decorator:
                signature = get_signature(temp_line)
                self.lines += [
                    " " * reference_indent + signature + " = locals()['.internals']['.decorator'](%s)" % signature
                ]
                self.decorator = False
        else:
            ## update the lineno before so the loops positions are lineno based ##
            self.lineno += 1
            temp_line = custom_adjustment(self, self.line, reference_indent)
            ## for multiple except catches ##
            if self.catch:
                ## end of except catches ##
                if reference_indent < self.catch[1]:
                    self.lines += [" " * (4 * self.catch[0] + self.catch[1]) + "else:"]
                    self.lines += indent_lines(
                        [
                            "locals()['.internals']['.continue_error'] = False",
                            "raise locals()['.internals']['.error']",
                        ],
                        self.catch[1] + (4 * (self.catch[0] + 1)),
                    )
                    self.lines += indent_lines(["finally:", "    pass"], self.catch[1])
                    self.catch = []
                elif reference_indent == self.catch[1]:
                    temp = temp_line[0].lstrip()
                    flag = temp.startswith("except:") or temp.startswith("except ")
                    if flag:
                        self.lines += [" " * (4 * self.catch[0] + self.catch[1]) + "else:"]
                        temp_line = except_catch_adjust(temp_line[0], [])
                        temp_line = indent_lines(temp_line, 4 * self.catch[0])
                        self.catch[0] += 1
                    else:
                        self.lines += [" " * (4 * self.catch[0] + self.catch[1]) + "else:"]
                        self.lines += indent_lines(
                            [
                                "locals()['.internals']['.continue_error'] = False",
                                "raise locals()['.internals']['.error']",
                            ],
                            self.catch[1] + (4 * (self.catch[0] + 1)),
                        )
                        if not temp.startswith("finally:") or temp.startswith("finally "):
                            self.lines += indent_lines(["finally:", "    pass"], self.catch[1])
                        self.catch = []
                else:
                    temp_line = indent_lines(temp_line, 4 * self.catch[0])
            self.lines += temp_line
        setup_next_line(self, self.char, self.indentation)
    else:
        reference_indent = self.indentation
        setup_next_line(self)
    ## make a linetable if using a running generator ##
    ## for the linetable e.g. for lineno_adjust e.g. compound statements ##
    if running and self.char == "\n":
        self.linetable += [self.lineno]
    # if indent_adjust:
    #     line += " " * indent_adjust
    ## 'space' is important (otherwise we get more indents than necessary) ##
    self.space = self.index


def block_adjust(
    self: object,
    current_lines: list[str],
    new_lines: list[str],
    final_line: str,
) -> None:
    """
    Checks if lines that were adjusted because of value yields
    are in a block statement and therefore needs adjusting

    Also, the new_lines do need to be indented accordingly
    e.g. to the final_line or specfic adjustment, and the
    jump_positions of any loops need to be recorded (e.g.
    from yield_adjust for 'yield from ...')
    """
    ## make sure any loops are recorded (necessary for 'yield from ...' adjustment) ##
    ## and the lineno is updated ##
    loop = False
    for self.lineno, line in enumerate(new_lines, start=self.lineno + 1):
        number_of_indents = get_indent(line)
        if is_loop(line[number_of_indents:]):
            record_jumps(self, number_of_indents)
            loop = number_of_indents
            continue
        if loop and number_of_indents <= loop:
            self.jump_positions[-1][1] = self.lineno
            loop = False
    if loop:
        self.jump_positions[-1][1] = self.lineno
    ## check for adjustments in the final line ##
    number_of_indents = get_indent(final_line)
    temp_line = final_line[number_of_indents:]
    check = lambda expr: temp_line.startswith(expr) and temp_line[len(expr)] in " :"
    if temp_line[:1] == "@":
        temp_line = temp_line[1:]
        signature = get_signature(temp_line, True)
        if signature[1]:
            temp_line = "locals()['.internals']['partial'](%s, %s)" % signature
        else:
            temp_line = signature[0]
        if self.decorator:
            temp_line = "locals()['.internals']['.decorator'](%s)" % temp_line
        else:
            self.decorator = True
        final_line = " " * number_of_indents + "locals()['.internals']['.decorator'] = " + temp_line
    elif is_definition(temp_line):
        collect_definition(
            self,
            self.index - len(self.line) + 1,
            number_of_indents,
        )
        if self.decorator:
            lines += [get_signature(temp_line) + " = locals()['.internals']['.decorator']"]
            self.decorator = False
    elif temp_line.startswith("while "):
        ## the end of the loop needs to be appended with the new_lines ##
        ## locals()[".args"] += next(...)
        ## while locals()[".args"].pop():
        ##     ...
        ##     locals()[".args"] += next(...)
        self.stack_adjuster += [[number_of_indents] + indent_lines(new_lines, number_of_indents + 4)]
    ## needs to indent itself and all other lines until the end of the block ##
    ## Note: only elif since if statements should be fine ##
    elif check("elif"):
        ## +4 to encapsulate in an else statement +2 to make it an 'if' statement ##
        final_line = " " * (number_of_indents + 4) + final_line[number_of_indents + 2 :]
        self.lines = (
            current_lines
            + [" " * number_of_indents + "else:"]
            + indent_lines(new_lines, number_of_indents + 4)
            + [final_line]
        )
        return
    elif check("except"):
        ## if it's already excepting ##
        if self.catch:
            self.lines += [" " * (4 * self.catch[0] + self.catch[1]) + "else:"]
            self.lines += indent_lines(except_catch_adjust(final_line, new_lines), 4 * self.catch[0])
            self.catch[0] += 1
        else:
            ## except_adjust automatically does the indentation ##
            self.lines, indent = except_adjust(current_lines, new_lines, final_line)
            self.catch = [1, indent]
        return
    self.lineno += 1
    self.lines = current_lines + indent_lines(new_lines, number_of_indents) + [final_line]


def string_collector_adjust(self: object) -> None:
    """Adjust the string collector in case of any value yields in the f-strings"""
    string_collected, self.prev, adjustments, fixed_lines = string_collector_proxy(
        self.index, self.char, self.prev, self.source_iter, self.line, self.source
    )
    if adjustments:
        ## since we have adjustments we need to adjust the chars after it ##
        # adjustments_start, line_start, self.index, fixed_lines = unpack(
        #     self.line, source=self.source, index=self.index, fixed_lines=fixed_lines
        # )
        # print(adjustments_start, line_start)
        # line_start = " " * get_indent(self.line)# + line_start.lstrip()
        adjustments_end, line_end, self.index, fixed_lines = unpack(
            source_iter=self.source_iter,
            source=self.source,
            index=self.index,
            fixed_lines=fixed_lines,
        )
        final_adjustments, final_line = (
            adjustments + adjustments_end,
            self.line + string_collected + line_end,
        )
        add_fixed_lines(self, fixed_lines)
        block_adjust(self, self.lines, final_adjustments, final_line)
        self.depth, self.ID = 0, ""
        self.indentation = get_indent(self.lines[-1])
        setup_next_line(self, self.source[self.index], self.indentation)
        self.space = self.index
        return
    add_fixed_lines(self, fixed_lines)
    self.line += string_collected


def add_fixed_lines(self: object, fixed_lines: int) -> None:
    """
    Adjusts the lineno in the linetable for lines that have expanded to 
    multiple lines long that represent the same line
    """
    if fixed_lines:
        self.linetable += [self.lineno] * fixed_lines


def update_stack(self, reference_indent: int = 0) -> None:
    while self.stack_adjuster and reference_indent <= self.stack_adjuster[-1][0]:
        self.lines += self.stack_adjuster.pop()[1:]
        self.lineno += 2
        self.linetable += [self.lineno]


def clean_source_lines(gen: object, running: bool = False) -> None:
    """
    source: str

    returns source_lines: list[str],return_linenos: list[int]

    1. fixes any indentation issues (when ';' is used) and skips empty lines
    2. split on "\n", ";", and ":"
    3. join up the line continuations i.e. "\\ ... " will be skipped

    additionally, custom_adjustment will be called on each line formation as well

    Note:
    jump_positions: are the fixed list of (lineno,end_lineno) for the loops (for and while)
    jump_stack: jump_positions currently being recorded (gets popped into jump_positions once
                    the reference indent has been met or lower for the next line that does so)
                    it records a tuple of (reference_indent,jump_position_index)
    stack_adjuster: adjusts the lines with new lines from unpacking a while loop condition
    fixed_lineno: the lineno of the current line fixed at the first line of unpacking

    
    Additional info for future reference:
    string_collector_adjust and source_ID_adjust are the two gateways to unpack and unpack yield
    """
    ## create a mutable instance ##
    self = type("", tuple(), {})()
    ## for loop adjustments ##
    (
        self.catch,
        self.linetable,
        self.jump_positions,
        self.jump_stack,
        self.stack_adjuster,
        self.lines,
        self.indented,
        self.decorator,
        self.assigned, ## to detect value yields without brackets ##
        self.lineno,
        self.fixed_lines,
        self.depth,
        self.space,
        self.indent_adjust,
        self.indentation,
        self.fixed_lineno,
        self.ID,
        self.line,
        self.prev,
    ) = (
        [],
        [],
        [],
        [],
        [],
        [],
        False,
        False,
        False,
        0,
        0,
        0,
        0,
        0,
        4,
        None,
        "",
        " " * 4,
        (0, 0, ""),
    )
    ## setup source as an iterator and making sure the first indentation's correct ##
    ## we need to make sure the source is saved for skipping for line continuations ##
    self.source = skip_source_definition(gen._internals["source"])
    self.source = self.source[get_indent(self.source) :]
    self.source_iter = enumerate(self.source)
    ## enumerate since I want the loop to use an iterator but the
    ## index is needed to retain it for when it's used on get_indent
    for self.index, self.char in self.source_iter:
        ## collect strings ##
        if self.char == "'" or self.char == '"':
            string_collector_adjust(self)
        ## makes the line singly spaced while retaining the indentation ##
        elif self.char == " ":
            self.line, self.space, self.indented = singly_space(
                self.index, self.char, self.line, self.space, self.indented
            )
            if self.indented == 1:
                update_stack(self, get_indent(self.line))
                self.indentation = 2
        ## join everything after the line continuation until the next \n or ; ##
        elif self.char == "\\":
            skip_line_continuation(self.source_iter, self.source, self.index)
            add_fixed_lines(self, 1)
            ## in case of a line continuation without a space before (whitespace after is removed) ##
            ## Note: i.e. 'func        ()' is valid in python ##
            if self.space + 1 != self.index:
                self.line += " "
                self.space = self.index
        ## create new line ##
        elif self.char in "#\n;" or (self.char == ":" and self.source[self.index + 1 : self.index + 2] != "="):
            self.ID = ""
            if running and self.char == "\n" and (self.depth or self.fixed_lineno is not None):
                ## adjusts the linetable for closing opened brackets ##
                if self.fixed_lineno is None:
                    self.lineno += 1
                    self.fixed_lineno = self.lineno
                    self.lines += [""]
                self.linetable += [self.fixed_lineno]
                ## append the current line ##
                self.lines[-1] += self.line
                self.line = ""
                if self.depth == 0:
                    self.fixed_lineno = None
                    ## append the current line ##
                    setup_next_line(self, self.char, self.indentation)
            else:
                self.fixed_lineno = None
                append_line(self, running)
                self.depth = 0
            self.assigned = False
        else:
            self.line += self.char
            ## detect value yields: [yield] and {yield} is not possible only (yield) ##
            self.depth = update_depth(self.depth, self.char)
            ## '... = yield ...' and '... = yield from ...'
            if not self.assigned and self.char == "=":
                self.assigned = True
            if (self.depth or self.assigned) and self.char.isalnum():
                source_update_ID(
                    self,
                    self.source[self.index + 1 : self.index + 2],  ## : index + 2 in case of IndexError ##
                    running,
                )
            else:
                self.ID = ""
    ## in case you get a for loop at the end and you haven't got the end jump_position ##
    ## then you just pop them all off as being the same end_lineno ##
    ## note: we don't need a reference indent since the line is over e.g. ##
    ## the jump_stack will be popped if it exists ##
    update_jump_positions(self)
    update_stack(self)
    ## are no longer needed ##
    gen._internals.update(
        {
            "source_lines": self.lines,
            "jump_positions": self.jump_positions,
            "linetable": self.linetable,
        }
    )


def source_update_ID(
    self: object,
    next_char: str,
    running: bool,
) -> None:
    """
    Handles ID in clean_source_lines to collect lambdas, value yields, and ternary expressions

    This is to lexically collect lambdas, value yields, and ternary expressions through identification

    This function is one of the gateways to the use of the unpack and unpack_yield functions
    """
    ## in case of ... ... (otherwise you keep appending the ID) e.g. new ID ##
    if self.space + 1 == self.index:        
        self.ID = ""
    self.ID += self.char
    # lambda expression #
    if self.ID == "lambda" and next_char in " :\\":
        # ([], "lambda x: x", 0, "x")
        temp = collect_lambda(self.line, self.source_iter, self.source, self.prev)
        self.lines += temp[0]
        self.line += temp[1]
        self.fixed_lines += temp[2]
        self.char = temp[3]
        self.indentation = get_indent(self.line)
        setup_next_line(self, self.char, self.indentation)
        self.lineno += 1
        self.ID = ""
    # send value yield e.g. ... = (yield ...) or ... = (yield from ...)
    # and send yields e.g. ... = yield ... or ... = yield from ...
    elif self.ID == "yield" and next_char in " )]}\n;\\":
        self.ID = ""
        ## send value yields ##
        if self.depth:
            self.depth = 0
            unpack_yield(self, running, self.line)
        ## send yields ##
        else:
            ## you can have yield from as a send yield ##
            self.index += 1
            yield_from = self.source[self.index:].lstrip().startswith("from ")
            if yield_from:
                ## skip to the from ##
                for self.index, self.char in self.source_iter:
                    if self.char.isalnum():
                        self.ID += self.char
                    elif self.ID:
                        break
            ## -5 for 'yield' relative to the line collected prior ##
            self.line = self.line[:-5]
            unpack_yield(self, running, yield_from=yield_from)
    ## ternary statement e.g. ... if ... else ... ##
    elif self.ID == "if" and next_char in " \\" and self.line[:-2].lstrip():
        ## _ would be self.index, however, we don't need it on this iteration ##
        new_lines, final_line, _, fixed_lines = unpack(
            self.line, self.source_iter, source=self.source, index=self.index
        )
        add_fixed_lines(self, fixed_lines)
        self.block_adjust(self, new_lines, final_line)


def unpack_yield(self, running: bool, line: Union[str, None] = None, yield_from: bool = False) -> None:
    """
    proxy to unpack value yields

    parameter 'line' is needed incase self.line changes
    
    Note:
    This function will append the lines to self.lines and therefore
    does some of the adjustments done by ...
    """
    indents = get_indent(self.line)
    new_lines, final_line, self.index, fixed_lines = unpack(
        line, self.source_iter, self.source, index=self.index
    )
    add_fixed_lines(self, fixed_lines)
    if line is None:
        head = "yield "
        if yield_from:
            head += " from "
        new_lines += yield_adjust(head + final_line, "")
        final_line = self.line + "locals()['.internals']['.send']"
    elif line.lstrip().startswith("yield "):
        final_line = "return " + final_line.lstrip()
    final_line = " " * indents + final_line.lstrip()
    if self.line[indents:].startswith("elif "):
        self.indent_adjust = 4
    length_before = len(self.lines)
    block_adjust(self, self.lines, new_lines, final_line)
    if running:
        self.linetable += [self.lineno] * (len(self.lines) - length_before)
    ## def ... ##
    if is_definition(final_line[get_indent(final_line) :]):
        setup_next_line(self)
    else:
        self.indentation = get_indent(self.lines[-1]) + self.indent_adjust
        setup_next_line(self, self.source[self.index], self.indentation)
    if self.indent_adjust:
        self.line = " " * self.indentation
    ## setup the variables for the next line ##
    self.assigned = False    
    ## important to ensure the indentation is correct ##
    self.space = self.index


def clean_lambda(self: GeneratorType, FUNC: FunctionType) -> None:
    """
    determine what expression is formed when the lambda expression gets called
    1. value yields - unpack
    2. generator expression - unpack_genexpr
    """
    self._internals["source"] = expr_getsource(FUNC)
    source = unpack_lambda(self._internals["source"])[0]
    ## tries to figure out what it is ##
    # Non Generator, Generator, generator expression
    type = check_expression(source)
    if type == "<genexpr>":
        genexpr_adjust(self, source)
    ## should only have a single value yield at depth == 1 ##
    elif type == "<Generator>":
        lines, final_line, _, _ = unpack(source)
        self._internals["source_lines"] = lines + [final_line]
        self._internals["lineno"] = 1
    else:
        raise TypeError(
            "based on the source code retrieved the expression that will be created from the given lambda expression is an invalid initializer for a Generator"
        )


def genexpr_adjust(self: GeneratorType, source: str) -> None:
    """Adjusts for an initialized generator expression"""
    self._internals["source_lines"] = unpack_genexpr(source)
    ## add the jump_positions ##
    positions, length = [], len(self._internals["source_lines"])
    for index, line in enumerate(self._internals["source_lines"], start=1):
        if not line[get_indent(line) :].startswith("for "):
            break
        positions += [[index, length]]
    self._internals["jump_positions"] = positions
    ## set the first iterator and determine the lineno ##
    first_iter = self._locals().pop(".0")
    if ".internals" not in self._locals():
        ## the internally set iterator ##
        self._locals()[".internals"] = {".4": first_iter}
    ## change the offsets into indents + check if it's running ##
    
    ## we know a generator expression is running if it has more than one variable.
    ## Its for loop cannot exist without at least one more variable present than '.0' 
    ## , however, it is possible to nonlocally override this so cannot use this approach
    ## and instead use inspect.getgeneratorstate

    track_adjust(self._locals()[".internals"])
    if getgeneratorstate(self) == "GEN_CREATED":
        self._internals["lineno"] = 1
    else:
        self._internals["lineno"] = length


def check_expression(source: str) -> str:
    """Checks if there are any yields or if there is a single generator expression present"""
    ID, depth, prev, expression = (
        "",
        0,
        (0, 0, ""),
        "",
    )
    source_iter = enumerate(source)
    for index, char in source_iter:
        ## skip all strings if not in genexpr
        if char == "'" or char == '"':
            _, prev = string_collector_proxy(index, char, prev, source_iter)
        ## detect brackets
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        if depth:
            ## record ID ##
            if char.isalnum():
                ID += char
                if depth == 1:
                    next_char = source[index + 1 : index + 2]
                    if ID == "for" and next_char in " \\":
                        expression = "<genexpr>"
                    if ID == "yield" and next_char in " \\)":
                        expression = "<Generator>"
            else:
                ID = ""
    temp = source[index + 1 :]
    if temp and not temp.isspace():
        return ""
    return expression


### when is it def
### when does indentation get reduced

def end_offset_adjust(source: str) -> int:
    """
    In extract function to be inclusive of 
    lines that are not indented and are 
    empty space we must trim the offset
    by a number of characters
    """
    ## we shouldn't encounter and end block because this
    ## is already handled at the end of extract_function

    # needed to trim the current line after the function body #
    new_line = False
    for index, char in enumerate(source[::-1]):
        if char != "\n":
            if new_line:
                return index + 1
        else:
            new_line = True
    raise ValueError("could not find end offset from an unexpected source code format")


def extract_function(source_code: str) -> GeneratorType:
    """Extracts each function and its offset from the source code"""
    ID, indent, prev, indented, offsets, reference_indent, line_index, depth, past_def, past_signature = (
        "",
        0,
        (0, 0, ""),
        False,
        [],
        [],
        0,
        0,
        False,
        False,
    )
    source_iter = enumerate(source_code)
    for index, char in source_iter:
        if not indented:
            if char == " ":
                indent += 1
            elif index - (indent + 1) != line_index:
                if reference_indent and indent <= reference_indent[-1]:
                    past_signature = False
                while reference_indent and indent <= reference_indent[-1]:
                    ## remove the reference indent then yield and continue ##
                    reference_indent.pop()
                    offset = offsets.pop()
                    yield offset, index - end_offset_adjust(source_code[offset:index - 1])
                indented = True
        ## skip all strings (we only want the offsets) ##
        if char == "'" or char == '"':
            _, prev, _ = string_collector_proxy(index, char, prev, source_iter)
        elif char == "\\":
            skip_line_continuation(source_iter, source_code, index)
        elif char == "\n":
            ## compound definition finished ##
            if past_signature and past_signature[0]:
                past_signature[0] = False # only allowed to check once
                line = source_code[past_signature[1] + 1:index]
                # print(line)
                if line and not line.isspace():
                    ## remove the reference indent then yield and continue ##
                    reference_indent.pop()
                    yield offsets.pop(), index
                    indented = True
                    past_signature = False
                
            line_index = index
            ID, indent, indented = "", 0, False
            continue
        elif char.isalnum():
            ID += char
        else:
            ## we're in a function definition ##
            if ID == "def" and char == " ":
                past_def = True
                temp = index - 4 - indent
                if temp == -1:
                    temp = 0
                offsets += [temp]
                reference_indent += [indent]
            ID = ""
            ## to detect and locate end of function signature ##
            if past_def and not past_signature:
                if char in "({[":
                    depth += 1
                elif char in ")}]":
                    depth -= 1
                elif depth == 0 and char == ":":
                    past_signature = [True, index]
                    past_def = False

    while offsets:
        yield offsets.pop(), None
