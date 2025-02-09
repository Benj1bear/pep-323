import gc
import inspect
import textwrap
from typing import Iterable, Literal, overload

# from types import GeneratorType


class Code:
    """This class helps manipulating code"""

    def __init__(self, code: str, running_line: int = 0, generator=None):
        self.code = code  # all code not in lines
        self.running_line = running_line
        self.generator = generator

    @classmethod
    def from_generator(cls, running_gen) -> "Code":
        return cls(
            inspect.getsource(running_gen.gi_code),
            cls.get_runnning_line(running_gen),
            running_gen,
        )

    @property
    def lines(self) -> list[str]:
        return self.code.split("\n")

    @staticmethod
    def get_runnning_line(running_gen) -> int:
        return running_gen.gi_frame.f_lineno - running_gen.gi_code.co_firstlineno

    @property
    def dedent(self) -> "Code":
        return Code(textwrap.dedent(self.code))

    @property
    def indent(self) -> str:
        return textwrap.indent(str(self), "    ")

    def __next__(self):
        assert self.generator is not None
        a = next(self.generator)
        self.running_line = self.get_runnning_line(self.generator)
        return a

    @overload
    def __getitem__(self, key: int) -> str: ...

    @overload
    def __getitem__(self, key: slice) -> "Code": ...

    def __getitem__(self, key):
        if isinstance(key, int):
            return self.lines[key]
        return Code("\n".join(self.lines[key]))

    def __str__(self) -> str:
        return self.code  # "\n".join(self.lines)

    def __repr__(self) -> str:
        return "\n".join(self.lines)

    def __radd__(self, b) -> "Code":
        return Code(str(b) + self.code + "\n")

    def __add__(self, b) -> "Code":
        return Code(self.code + str(b) + "\n")

    @property
    def running_level(self) -> int:
        return self.line_level(self.running_line)

    @property
    def running_line_txt(self) -> str:
        return self[self.running_line]

    @property
    def running_in_block(self) -> bool:
        return self.running_level > 1

    @property
    def block(self) -> Literal["root", "while", "if", "else:"]:
        if self.running_in_block:
            return self[self.block_start_line].strip().split(" ")[0]
        else:
            return "root"

    @property
    def block_start_line(self) -> int:
        line = self.running_line - 1
        while self.running_level == self.line_level(line):
            line -= 1
        return line

    @property
    def block_end_line(self) -> int:
        line = self.running_line + 1
        while self.running_level == self.line_level(line):
            line += 1
        return line

    @property
    def block_text(self) -> "Code":
        return self[self.block_start_line : self.block_end_line]

    @property
    def scope_after(self) -> "Code":
        return self[self.running_line + 1 : self.line_scope_after]

    @property
    def line_scope_after(self) -> int:
        line = self.running_line
        while self.running_level == self.line_level(line):
            line += 1
        return line

    @property
    def next_scope_line(self) -> int:
        return self.line_scope_after + 1

    def line_level(self, line: int) -> int:
        return self.level(self[line])

    @staticmethod
    def level(line: str) -> int:
        stripped = line.lstrip()
        level = len(line) - len(stripped)
        return level // 4


def get_implicit_iterator_in_for_loop(a):
    """gets the implicit iterator in a for loop, this is as hacky as it could be,
    reliying in python internals that are only be exposed to the garbage collector.

    a = [1,2,3]
    for i in a:
        h = get_implicit_iterator_in_for_loop(a)
        next(h) => 2

    """
    for i in [obj for obj in gc.get_referrers(a) if isinstance(obj, Iterable)]:
        if str(type(i)) == "<class 'list_iterator'>":
            return i


def get_implicit_iterator_in_for_loop_everywhere():
    """gets the implicit iterator in a for loop, this is as hacky as it could be,
    reliying in python internals that are only be exposed to the garbage collector.

    for i in [1,2,3]:
        h = get_implicit_iterator_in_for_loop(a)
        next(h) => 2

    """
    for i in [obj for obj in gc.get_objects() if isinstance(obj, Iterable)]:
        if str(type(i)) == "<class 'list_iterator'>":
            return i


###
# cuando serialices, guarda el codigo en texto y las variables, haz que el codigo sea una funcion con cualquier nombre
# cuando deserialices executa el codigo con las variables guardadas.


def my_copy(generator):
    """this function taske the generator code and localizes the line being executed
    then we create a new piece of code and use exec for producing a new generator
    that would mimic the state of the previous one.

    for instance for the generator being executed :

    def gen_test():
        a = 1
        b = 2
        b +=10
        yield a
        while True:
            yield b    X code is here now
            b +=1

    t = gen_test()
    next(t) -> 1
    next(b) -> 11

    my_copy(t) -> produces a artificial generator as TEXT:

        def gen_test():
            a,b = 1, 11 # from the variables stored

            b +=1 # the rest of the while loop
            while True:  # the while loop untouched
                yield b    X code is here now
                b +=1
    and then executes it using exec and saves variables with it.

    we  may need to store locals globals as well for the pickling

    """

    code = Code.from_generator(generator)
    args = generator.gi_frame.f_locals.copy()
    args = ",".join(f"{k}={v}" for k, v in args.items())

    # function def, not really needed, but fine
    new_code = Code(f"def saved({args}):\n")
    line = code.running_line + 1

    if code.block in ["if", "else:", "elif"]:
        new_code += "    if True:"
        new_code += "        pass"
    elif code.block == "while":
        new_code += code.scope_after.dedent.indent
        line = code.block_start_line

    # main code
    new_code += code[line:]

    # executor
    new_code += f"n = saved({args})"
    # print(new_code.code)
    exec(new_code.code)
    return eval("n")
