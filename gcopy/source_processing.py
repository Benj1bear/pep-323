#################################################
### cleaning/extracting/adjusting source code ###
#################################################
from utils import get_instructions, version_info, getcode, getframe, attr_cmp, chain
from inspect import getsource, findsource
from typing import Iterable, GeneratorType, FrameType, Any


def get_indent(line: str) -> int:
    """Gets the number of spaces used in an indentation"""
    count = 0
    for char in line:
        if char != " ":
            break
        count += 1
    return count


def lineno_adjust(FUNC: Any, frame: FrameType = None) -> int:
    """
    unpacks a line of compound statements
    into lines up to the last instruction
    that determines the adjustment required
    """
    if frame is None:
        frame = getframe(FUNC)
    line, current_lineno, instructions = (
        [],
        frame.f_lineno,
        get_instructions(frame.f_code),
    )
    ## get the instructions at the lineno ##
    for instruction in instructions:
        lineno, obj = instruction.positions.lineno, (
            list(instruction.positions[2:]),
            instruction.offset,
        )
        if not None in obj[0] and lineno == current_lineno:
            ## get the lines ##
            line = [obj]
            for instruction in instructions:
                lineno, obj = instruction.positions.lineno, (
                    list(instruction.positions[2:]),
                    instruction.offset,
                )
                if lineno != current_lineno:
                    break
                line += [obj]
            break
    ## add the lines
    if line:
        index, current, lasti = 0, [0, 0], frame.f_lasti
        for pos, offset in line.sort():
            if offset == lasti:
                return index
            if pos[0] > current[1]:  ## independence ##
                current = pos
                index += 1
            elif pos[1] > current[1]:  ## intersection ##
                current[1] = pos[1]
    raise ValueError("f_lasti not encountered")


def unpack_genexpr(source: str) -> list[str]:
    """unpacks a generator expressions' for loops into a list of source lines"""
    lines, line, ID, depth, prev, has_for, has_end_if = (
        [],
        "",
        "",
        0,
        (0, 0, ""),
        False,
        False,
    )
    source_iter = enumerate(source[1:-1])
    for index, char in source_iter:
        if char in "\\\n":
            continue
        ## collect strings
        if char == "'" or char == '"':
            line, prev = string_collector_proxy(index, char, prev, source_iter, line)
            continue
        if (
            char == "("
        ):  ## we're only interested in when the generator expression ends in terms of the depth ##
            depth += 1
        elif char == ")":
            depth -= 1
        ## accumulate the current line
        line += char
        ## collect IDs
        if char.isalnum():
            ID += char
        else:
            ID = ""
        if depth == 0:
            if ID == "for" or ID == "if" and next(source_iter)[1] == " ":
                if ID == "for":
                    lines += [line[:-3]]
                    line = line[-3:]  # +" "
                    if not has_for:
                        has_for = len(lines)  ## should be 1 anyway
                elif has_for:
                    lines += [
                        line[:-2],
                        source[index:-1],
                    ]  ## -1 to remove the end bracket - is this necessary?
                    has_end_if = True
                    break
                else:
                    lines += [line[:-2]]
                    line = line[-2:] + " "
                # ID="" ## isn't necessary because you don't get i.e. 'for for' or 'if if' in python syntax
    if has_end_if:
        lines = lines[has_for:-1] + (lines[:has_for] + [lines[-1]])[::-1]
    else:
        lines = lines[has_for:] + (lines[:has_for])[::-1]
    ## arrange into lines
    indent = " " * 4
    return [indent * index + line for index, line in enumerate(lines, start=1)]


def skip_line_continuation(source_iter: Iterable, source: str, index: int) -> None:
    """skips line continuations in source"""
    whitespace = get_indent(source[index + 1 :])  ## +1 since 'index:' is inclusive ##
    ## skip the whitespace after newline ##
    skip(
        source_iter, whitespace + get_indent(source[index + 1 + whitespace + 1 :])
    )  ## skip the current char, whitespace, newline and whitespace after ##


def skip_source_definition(source: str) -> str:
    """Skips the function definition and decorators in the source code"""
    ID, source_iter = "", enumerate(source)
    for index, char in source_iter:
        ## decorators are ignored ##
        while char == "@":
            while char != "\n":
                index, char = next(source_iter)
            index, char = next(source_iter)
        if char.isalnum():
            ID += char
            if len(ID) == 3:
                if ID == "def" and next(source_iter)[1] == " ":
                    while char != "(":
                        index, char = next(source_iter)
                    break
                return source
        else:
            ID = ""
    depth = 1
    for index, char in source_iter:
        if char == ":" and depth == 0:
            return source[index + 1 :]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
    raise SyntaxError("Unexpected format encountered")


def string_collector_proxy(
    index: int,
    char: str,
    prev: tuple[int, int, str],
    iterable: Iterable,
    line: str = None,
    source: str = None,
) -> tuple[list[str], str, int]:
    """Proxy function for usage when collecting strings since this block of code gets used repeatedly"""
    # get the string collector type ##
    if prev[0] + 2 == prev[1] + 1 == index and prev[2] == char:
        string_collector, temp_index = collect_multiline_string, 3
    else:
        string_collector, temp_index = collect_string, 1
    ## determine if we need to look for f-strings in case of value yields ##
    f_string = False
    if (
        source and version_info >= (3, 6) and source[index - temp_index] == "f"
    ):  ## f-strings ##
        f_string = source[index:]  ## use the source to determine the extractions ##
    temp_index, temp_line = string_collector(iterable, char, f_string)
    prev = (index, temp_index, char)
    if source:
        ## lines (adjustments) + line (string collected) ##
        line += temp_line.pop()
        ## if we have adjustments then we need to ensure that the line is adjusted ##
        ## we have to unpack_adjust only if we got a yield ##
        if temp_line:
            temp_lines, final_line, offset = unpack(
                line, iterable
            )  ## line shouldn't be None ##
            line = final_line
        return line, prev, temp_lines
        # line+=temp_line ## line shouldn't be None otherwise we don't get an adjustment ##
    if line is not None:
        line += temp_line
    return line, prev


def collect_string(
    source_iter: Iterable, reference: str, source: str = False
) -> tuple[int, str | list[str]]:
    """
    Collects strings in an iterable assuming correct
    python syntax and the char before is a qoutation mark

    Note: make sure source_iter is an enumerated type
    """
    line, backslash, left_brace, lines = reference, False, -2, []
    for index, char in source_iter:
        if char == reference and not backslash:
            line += char
            break
        line += char
        backslash = False
        if char == "\\":
            backslash = True
        ## detect f-strings for value yields ##
        if source and char == "{":
            if index - 1 != left_brace:
                temp_lines, final_line, right_brace = unpack_fstring(
                    source, source_iter, left_brace
                )
                ## update ##
                lines += temp_lines
                line += final_line
            left_brace = index
    if source:
        return index, lines + [line]  ## we have to add it for the f-string case ##
    return index, line


def collect_multiline_string(
    source_iter: Iterable, reference: str, source: str = False
) -> tuple[int, str | list[str]]:
    """
    Collects multiline strings in an iterable assuming
    correct python syntax and the char before is a
    qoutation mark

    Note: make sure source_iter is an enumerated type

    if a string starts with 3 qoutations
    then it's classed as a multistring
    """
    line, backslash, prev, count, left_brace, lines = reference, False, -2, 0, None, []
    for index, char in source_iter:
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
        ## detect f-strings for value yields ##
        if source and char == "{":

            ## needs fixing ##
            if left_brace and index - 1 != left_brace:
                temp_lines, final_line, right_brace = unpack_fstring(
                    source, source_iter, left_brace
                )
                ## update ##
                lines += temp_lines
                line += final_line
            left_brace = index
    if source:
        return index, lines + [line]  ## we have to add it for the f-string case ##
    return index, line


def unpack_fstring(
    source: str, source_iter: Iterable, start_index: int
) -> tuple[list[str], str, int]:
    """detects a value yield then adjusts the line for f-strings"""
    line, ID, depth, break_check, lines = "", "", 0, 0, []
    for index, char in source_iter:
        ## may need so that we can detect break_check < 0 to break e.g. } (f-string) ##
        if char == "{":
            break_check += 1
        elif char == "}":
            break_check -= 1
        if break_check < 0:
            break
        line += char
        if char == "(":  ## only () will contain a value yield ##
            depth += 1
        elif char == ")":
            depth -= 1
        if char.isalnum():
            ID += char
            if char == "yield" and depth == 1:
                ## value_yield adjust will collect the entire line (f-string in this case) ##
                return unpack(source[start_index:], source_iter, index, True)
        else:
            ID = ""
    return lines, "", index


def collect_definition(
    line: str,
    lines: list[str],
    lineno: int,
    source: str,
    source_iter: Iterable,
    reference_indent: int,
    prev: tuple[int, int, str],
) -> tuple[int, str, int, list[str]]:
    """
    Collects a block of code from source, specifically a
    definition block in the case of this modules use case
    """
    indent = reference_indent + 1
    while reference_indent < indent:
        ## we're not specific about formatting the definitions ##
        ## we just need to make sure to include them ##
        for index, char in source_iter:
            ## collect strings ##
            if char == "'" or char == '"':
                line, prev = string_collector_proxy(
                    index, char, prev, source_iter, line
                )
            ## newline ##
            elif char == "\n":
                break
            else:
                line += char
        ## add the line and get the indentation to check if continuing ##
        lineno += 1
        lines += [line]
        line, indent = "", get_indent(source[index + 1 :])
    ## make sure to return the index and char for the indentation ##
    return index, char, lineno, lines


def skip(iter_val: Iterable, n: int) -> None:
    """Skips the next n iterations in a for loop"""
    for _ in range(n):
        next(iter_val)


## Note: line.startswith("except") will need to put a try statement in front (if it's not there e.g. is less than the minimum indent) ##
## match case default was introduced in python 3.10
if version_info < (3, 10):

    def is_alternative_statement(line: str) -> bool:
        return line.startswith("elif") or line.startswith("else")

else:

    def is_alternative_statement(line: str) -> bool:
        return (
            line.startswith("elif")
            or line.startswith("else")
            or line.startswith("case")
            or line.startswith("default")
        )


is_alternative_statement.__doc__ = "Checks if a line is an alternative statement"


def is_definition(line: str) -> bool:
    """Checks if a line is a definition"""
    return (
        line.startswith("def ")
        or line.startswith("async def ")
        or line.startswith("class ")
        or line.startswith("async class ")
    )


########################
### code adjustments ###
########################
def skip_alternative_statements(
    line_iter: Iterable, current_min: int
) -> tuple[int, str, int]:
    """Skips all alternative statements for the control flow adjustment"""
    for index, line in line_iter:
        temp_indent = get_indent(line)
        temp_line = line[temp_indent:]
        if temp_indent <= current_min and not is_alternative_statement(temp_line):
            break
    return index, line, temp_indent


def control_flow_adjust(
    lines: list[str], indexes: list[int], reference_indent: int = 4
) -> tuple[list[str], list[int]]:
    """
    removes unreachable control flow blocks that
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an
    indentation of 4 (4 because we're in a function)

    It will also add 'try:' when there's an
    'except' line on the next minimum indent
    """
    new_lines, current_min = [], get_indent(lines[0])
    line_iter = enumerate(lines)
    for index, line in line_iter:
        temp_indent = get_indent(line)
        temp_line = line[temp_indent:]
        if temp_indent < current_min:
            ## skip over all alternative statements until it's not an alternative statement ##
            ## and the indent is back to the current min ##
            if is_alternative_statement(temp_line):
                end_index, line, temp_indent = skip_alternative_statements(
                    line_iter, temp_indent
                )
                del indexes[index:end_index]
                index = end_index
            current_min = temp_indent
            if temp_line.startswith("except"):
                new_lines = (
                    [" " * 4 + "try:"]
                    + indent_lines(new_lines)
                    + [line[current_min - 4 :]]
                )
                indexes = [indexes[0]] + indexes
        ## add the line (adjust if indentation is not reference_indent) ##
        if current_min != reference_indent:
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


def extract_iter(line: str, number_of_indents: int) -> str:
    """
    Extracts the iterator from a for loop

    e.g. we extract the second ... in:
    for ... in ...:
    """
    depth, ID, line_iter = 0, "", enumerate(line)
    for index, char in line_iter:
        ## the 'in' key word must be avoided in all forms of loop comprehension ##
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char.isalnum() and depth == 0:
            ID += char
            if ID == "in":
                if next(line_iter)[1] == " ":
                    break
                ID = ""
        else:
            ID = ""
    index += (
        2  ## adjust by 2 to skip the 'n' and ' ' in 'in ' that would've been deduced ##
    )
    iterator = line[index:-1]  ## -1 to remove the end colon ##
    ## remove the leading and trailing whitespace and then it should be a variable name ##
    if iterator.strip().isalnum():
        return line
    return line[:index] + "locals()['.%s']:" % number_of_indents


def iter_adjust(outer_loop: list[str]) -> tuple[bool, list[str]]:
    """adjust an outer loop with its tracked iterator if it uses one"""
    flag, line = False, outer_loop[0]
    number_of_indents = get_indent(line)
    if line[number_of_indents:].startswith("for "):
        outer_loop[0] = extract_iter(line, number_of_indents)
        flag = True
    return flag, outer_loop


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
    new_lines, flag, line_iter = [], False, enumerate(lines)
    for index, line in line_iter:
        indent = get_indent(line)
        temp_line = line[indent:]
        ## skip over for/while and definition blocks ##
        while (
            temp_line.startswith("for ")
            or temp_line.startswith("while ")
            or is_definition(temp_line)
        ):
            for index, line in line_iter:
                temp_indent = get_indent(line)
                if temp_indent <= indent:
                    break
                new_lines += [line]
            ## continue back ##
            indent = temp_indent
            temp_line = line[indent:]
        if temp_line.startswith("continue"):
            flag = True
            new_lines += ["break"]
        elif temp_line.startswith("break"):
            flag = True
            new_lines += ["locals()['.continue']=False", "break"]
            indexes = indexes[index:] + indexes[index] + indexes[:index]
        else:
            new_lines += [line]
    ## adjust it in case it's an iterator ##
    flag, outer_loop = iter_adjust(outer_loop)
    if flag:
        return [
            "    locals()['.continue']=True",
            "    for _ in (None,):",
        ] + indent_lines(new_lines, 8 - get_indent(new_lines[0])) + [
            "    if locals()['.continue']:"
        ] + indent_lines(
            outer_loop, 8 - get_indent(outer_loop[0])
        ), [
            indexes[0],
            indexes[0],
        ] + indexes + [
            pos[0]
        ] + list(
            range(*pos)
        )
    return indent_lines(lines, 4 - get_indent(lines[0])) + indent_lines(
        outer_loop, 4 - get_indent(outer_loop[0])
    ), indexes + list(range(*pos))


def has_node(line: str, node: str) -> bool:
    """Checks if a node has starting IDs that match"""
    ID, nodes, checks = "", [], node.split()
    for char in line:
        ## no strings allowed ##
        if char == "'" or char == '"':
            return False
        if char.isalnum():
            ID += char
        elif char == " ":
            if ID:
                nodes += [ID]
                for node, check in zip(nodes, checks):
                    if node != check:
                        return False
                if len(nodes) == len(checks):
                    return True
    return False


def send_adjust(line: str) -> tuple[int | None, str | None]:
    """Checks for variables assigned to yields for making adjustments"""
    parts, flag = line.split("="), 0
    for index, node in enumerate(parts):
        node = node[get_indent(node) :]
        if has_node(node, "yield from "):
            flag = 1
            break
        if has_node(node, "yield "):
            flag = 2
            break
    if flag:
        reciever = "="
        if flag == 2:
            reciever += "locals()['.send']"
        ## indicator       yield statement            assignments
        return flag, ["=".join(parts[index:]), "=".join(parts[:index]) + reciever]
    return None, None


def get_loops(
    lineno: int, jump_positions: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """
    returns a list of tuples (start_lineno,end_lineno) for the loop
    positions in the source code that encapsulate the current lineno
    """
    ## get the outer loops that contian the current lineno ##
    loops = []
    ## jump_positions are in the form (start_lineno,end_lineno) ##
    for (
        pos
    ) in (
        jump_positions
    ):  ## importantly we go from start to finish to capture nesting loops ##
        ## make sure the lineno is contained within the position for a ##
        ## loop adjustment and because the jump positions are ordered we ##
        ## can also break when the start lineno is beyond the current lineno ##
        if lineno < pos[0]:
            break
        if lineno < pos[1]:
            ## subtract 1 for 0 based indexing; it's only got one specific ##
            ## use case that requires it to be an array accessor ##
            loops += [(pos[0] - 1, pos[1] - 1)]
    return loops


def expr_getsource(FUNC: Any) -> str:
    """
    Uses co_positions or otherwise goes through the source code
    extracting expressions until a match is found on a code object
    basis to get the source

    Note:
    the extractor should return a string and if using a
    lambda extractor it will take in a string input but
    if using a generator expression extractor it will
    take a list instead
    """
    code_obj = getcode(FUNC)
    if code_obj.co_name == "<lambda>":
        ## here source is a : str
        source = getsource(code_obj)
        extractor = extract_lambda
    else:
        lineno = getframe(FUNC).f_lineno - 1
        ## here source is a : list[str]
        source = findsource(code_obj)[0][lineno:]
        extractor = extract_genexpr
    ## get the rest of the source ##
    if (3, 11) <= version_info:
        # start_line, end_line, start_col, end_col
        positions = code_obj.co_positions()
        is_source_list = isinstance(source, list)
        pos = next(positions, (None, None, None))[1:]
        current_min, current_max = pos[2:]
        if is_source_list:
            current_max_lineno = pos[1]
        for pos in positions:
            if pos[-2] and pos[-2] < current_min:
                current_min = pos[-2]
            if pos[-1] and pos[-1] > current_max:
                current_min = pos[-1]
            if is_source_list and pos[1] and pos[1] > current_max_lineno:
                current_max_lineno = pos[1]
        if is_source_list:
            source = "\n".join(source[: current_max_lineno + 1])
        return source[current_min:current_max]
    ## otherwise match with generator expressions in the original source to get the source code ##
    attrs = (
        "co_freevars",
        "co_cellvars",
        "co_firstlineno",
        "co_nlocals",
        "co_stacksize",
        "co_flags",
        "co_code",
        "co_consts",
        "co_names",
        "co_varnames",
        "co_name",
    )
    if (3, 3) <= version_info:
        attrs += ("co_qualname",)
    if isinstance(source, list):
        source = "\n".join(source)
    for col_offset, end_col_offset in extractor(source):
        try:  ## we need to make it a try-except in case of potential syntax errors towards the end of the line/s ##
            ## eval should be safe here assuming we have correctly extracted the expression - we can't use compile because it gives a different result ##
            temp_code = getcode(eval(source[col_offset:end_col_offset]))
            if attr_cmp(temp_code, code_obj, attrs):
                return source
        except:
            pass
    raise Exception("No matches to the original source code found")


###############
### genexpr ###
###############
def extract_genexpr(source: str) -> GeneratorType:
    """Extracts each generator expression from a list of the source code lines"""
    ID, is_genexpr, depth, prev = "", False, 0, (0, 0, "")
    source_iter = enumerate(source)
    for index, char in source_iter:
        ## skip all strings if not in genexpr
        if char == "'" or char == '"':
            _, prev = string_collector_proxy(index, char, prev, source_iter, _)
            continue
        ## detect brackets
        elif char == "(":
            temp_col_offset = index
            depth += 1
        elif char == ")":
            depth -= 1
            if is_genexpr and depth + 1 == genexpr_depth:
                yield col_offset, index + 1
                number_of_expressions += 1
                ID, is_genexpr = "", False
            continue
        ## record source code ##
        if depth and not is_genexpr:
            ## record ID ##
            if char.isalnum():
                ID += char
                ## detect a for loop
                if ID == "for":
                    genexpr_depth, is_genexpr, col_offset = depth, True, temp_col_offset
            else:
                ID = ""


##############
### lambda ###
##############
def extract_lambda(source_code: str) -> GeneratorType:
    """Extracts each lambda expression from the source code string"""
    ID, is_lambda, lambda_depth, prev, depth = "", False, 0, (0, 0, ""), 0
    source_code = enumerate(source_code)
    for index, char in source_code:
        ## skip all strings (we only want the offsets)
        if char == "'" or char == '"':
            _, prev = string_collector_proxy(index, char, prev, source_code)
            continue
        ## detect brackets (lambda can be in all 3 types of brackets) ##
        elif char in "({[":
            depth += 1
        elif char in "]})":
            depth -= 1
        ## record source code ##
        if is_lambda:
            if char == "\n;" or (
                char == ")" and depth + 1 == lambda_depth
            ):  # lambda_depth needed in case of brackets; depth+1 since depth would've got reduced by 1
                yield col_offset, index + 1
                ID, is_lambda = "", False
        else:
            ## record ID ##
            if char.isalnum():
                ID += char
                ## detect a lambda
                if ID == "lambda" and depth <= 1:
                    lambda_depth, is_lambda, col_offset = depth, True, index - 6
            else:
                ID = ""
    ## in case of a current match ending ##
    if is_lambda:
        yield col_offset, None


def update_lines(
    lines: list[str],
    line: str,
    final_line: str,
    char: str,
    source_iter: Iterable = None,
) -> tuple[list[str], str, int] | tuple[tuple[list[str], str, int], str]:
    """Updates the lines and final line with the new line"""
    lines += [line]
    final_line += line
    final_line += "locals()['.args'].pop()" + char
    if source_iter:
        return unwrap(line, source_iter, lines, final_line)[:-1], ""
    return lines, final_line, ""


def unwrap(
    line: str, source_iter: Iterable, lines: list[str], final_line: str
) -> tuple[list[str], str, str, int]:
    """unwraps the next unpacking in association with the current lines and final line"""
    temp_lines, temp_final_line, temp_end_index = unpack(line, source_iter, True)
    final_line += temp_final_line
    lines += temp_lines
    return lines, final_line, "", temp_end_index


def unpack(
    line: str, source_iter: Iterable, unwrapping: bool = False
) -> tuple[list[str], str, int]:
    """
    Unpacks value yields from a line into a
    list of lines going towards its right side
    """
    depth, lines, ID, line, end_index, final_line, prev = 0, [], "", "", 0, "", ""
    line_iter = enumerate(chain(line, source_iter))
    for end_index, char in line_iter:
        ## collect strings and add to the lines ##
        if char == "'" or char == '"':
            line, prev, temp_lines = string_collector_proxy(
                end_index, char, prev, line_iter, line
            )
            lines += temp_lines
            continue
        ## dictionary assignment ##
        if char == "[" and prev not in (" ", ""):
            lines, final_line, line, end_index = unwrap(
                line, source_iter, lines, final_line
            )
            continue
        if char == "\\":
            skip_line_continuation(line_iter, line, end_index)
            line += " "
            continue
        if char in ",<=>/|+-*&%@^":  ## splitting operators ##
            if end_index - 1 == operator:  ## since we can have i.e. ** or %= etc. ##
                lines, final_line, line = update_lines(lines, line, final_line)
                continue
            operator = end_index
        elif depth == 0 and char in "#:;\n":  ## split and break condition ##
            lines += [line]
            break
        elif char == ":":  ## must be a named expression if depth is not zero ##
            lines, final_line, line, ID = update_lines(lines, line, final_line, ID)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if unwrapping and depth < 0:
                break
        if depth:
            if char.isalnum():
                ID += char
                if ID == "yield":  ## unwrapping ##
                    lines, final_line, line, end_index = unwrap(
                        line, source_iter, lines, final_line
                    )
                elif ID in ["is", "in", "and", "or"]:
                    lines, final_line, line = update_lines(lines, line, final_line)
            else:
                ID = ""
        else:
            line += char
        prev = char
    return lines, final_line, end_index
