from sys import version_info
from inspect import getsource, currentframe, findsource, getframeinfo
from readline import get_history_item
from dis import get_instructions

#########################
### utility functions ###
#########################


def is_cli() -> bool:
    """Determines if using get_history_item is possible e.g. for CLIs"""
    try:
        get_history_item(0)
        return True
    except IndexError:
        return False


def yield_adjust(line, values) -> None:
    """adjusts value yields in a source line"""
    ## values is either the start positions or the f-string locations ##
    ## basically we go through each and extract the yield values ##
    pass # TODO DOES nothing?


def get_col_offset(frame) -> int | None :
    if version_info < (3, 11):
        # you put it out which is more efficient, but this is more readable
        lasti = frame.f_lasti
        for instruction in get_instructions(frame.f_code):
            if instruction.offset == lasti:
                return instruction.positions.col_offset
        raise ValueError("f_lasti not encountered")
    else:
        ## make an attr dict out of the tuple ##
        return getframeinfo(frame).positions.col_offset


def getframe(obj):
    """Gets the frame object from an object via commonly used attrs"""
    for attr in ["gi_frame", "ag_frame", "cr_frame"]:
        if hasattr(obj, attr):
            return getattr(obj, attr)
    raise AttributeError("frame object not found")


def empty_generator():
    """Creates a simple empty generator"""
    return
    yield


def dedent(text):
    """
    simplified version of dedent from textwrap that
    removes purely whitespace indentation from a string
    to the minimum indentation

    If you have python version 2.3 or higher you can use
    textwrap.dedent but I've decided to make an implementation
    specific version for python 2.2 and it should ideally be
    faster for its specific use case
    """
    ## because I'm only using this for functions source code ##
    ## we can use the indent from the first line as the ##
    ## minimum indent and remove unnecessary whitespace ##
    indent = get_indent(text)
    if indent == 0:
        return text
    text_iter, line, dedented, text = enumerate(text), -1, False, ""
    for index, char in text_iter:
        ## dedent the current line ##
        if not dedented:
            while char == " ":
                if not index - prev_split <= indent:
                    line = ""
                    break
                line += char
                index, char = next(text_iter)
            dedented = True
        ## collect the current line ##
        if char == "\n":
            prev_split, dedented = index, False
            if line.isspace():  ## remove unnecessary whitespace ##
                line = ""
            text += line + "\n"
            line = ""
        ## gather the chars ##
        else:
            line += char
    ## add the last line if it exists ##
    if line:
        text += line
    return text


def get_indent(line):
    """Gets the number of spaces used in an indentation"""
    count = 0
    for char in line:
        if char != " ":
            break
        count += 1
    return count


def lineno_adjust(FUNC, frame=None):
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


def collect_string(iter_val, reference, f_string=False):
    """
    Collects strings in an iterable assuming correct
    python syntax and the char before is a qoutation mark

    Note: make sure iter_val is an enumerated type
    """
    line, backslash, offsets = reference, False, tuple()
    for index, char in iter_val:
        if char == reference and not backslash:
            line += char
            break
        line += char
        backslash = False
        if char == "\\":
            backslash = True
        if f_string:
            if char == "{":
                offsets += (index,)
            elif char == "}":
                offsets[-1] += (index,)
    if offsets:
        return index, yield_adjust(line, offsets)
    return index, line


def collect_multiline_string(iter_val, reference, f_string=False):
    """
    Collects multiline strings in an iterable assuming
    correct python syntax and the char before is a
    qoutation mark

    Note: make sure iter_val is an enumerated type

    if a string starts with 3 qoutations
    then it's classed as a multistring
    """
    line, backslash, prev, count, offsets, ID, depth = (
        reference,
        False,
        -2,
        0,
        tuple(),
        "",
        0,
    )
    for index, char in iter_val:
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
        if f_string:
            if char == "(":  ## only () will contain a value yield ##
                depth += 1
            elif char == ")":
                depth -= 1
            if char.isalnum():
                ID += char
                if char == "yield":
                    pass
            else:
                ID = ""
            if char == "{":
                offsets += (index,)
            elif char == "}":
                offsets[-1] += (index,)
    if offsets:
        return index, yield_adjust(line, offsets)
    return index, line


def unpack_genexpr(source):
    """unpacks a generator expressions' for loops into a list of source lines"""
    lines, line, ID, depth, prev, has_for, has_end_if = (
        [],
        "",
        "",
        0,
        (0, ""),
        False,
        False,
    )
    source_iter = enumerate(source[1:-1])
    for index, char in source_iter:
        if char in "\\\n":
            continue
        ## collect strings
        if char == "'" or char == '"':
            if prev[0] - 1 == index and char == prev[1]:
                string_collector = collect_multiline_string
            else:
                string_collector = collect_string
            index, temp_line = string_collector(source_iter, char)
            prev = (index, char)
            line += temp_line
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
