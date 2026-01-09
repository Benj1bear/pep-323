# pep-323
Copyable Iterators (Generators)

This repo tries to implement a way of copying iterators.

We use code inspection and execution for achiving the result.


we create a new piece of code and use exec for producing a new generator
that would mimic the state of the previous one.

for instance for the generator being executed:

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

## User Guide

In this document I go through how to get a working example started and what you can explore/do with the Generator class and some of its nuances.

So long as you meet the assumptions requirements under the assumptions section in the custom_generator documentation you shouldn't have to rewrite your code. The only exception to this is for syntactical initiation of iterators and any other iterators not patched by ```patch_iterators``` (it patches builtin iterators only) i.e. 
```python
[1,2,3], (1,2,3), {"a":1,"b":2,"c":3}, {1,2,3}
# and
def test():
    yield 1

for i in test():
    pass
```
must be wrapped by the ```track``` function or any of the patched iterators after calling ```patch_iterators``` from gcopy.track inside this package for such iterators to be tracked (otherwise these are difficult or maybe impossible to save for transfer over states).
i.e.
```python
for i in [1,2,3]:
    ...
# should be rewritten as i.e.: #
for i in track([1,2,3]):
    ...
# or
for i in list([1,2,3]):
    ...
## and the generator ##
for i in track(test()):
    pass
```

To create a ```Generator``` type you simply wrap your generator in the Generator class as follows creating a custom ```Generator``` object:

```python
gen = Generator(simple_generator())
```

If you choose to provide an uninitialized generator function you will have the additional requirement to call it before calling the \_\_next\_\_ or \_\_iter\_\_ method.
i.e.

```python
gen = Generator(simple_generator)()
```

This additionally means we can decorate function generators using the ```Generator``` class treating the function as an uninitialized generator:

```python
@Generator
def simple_generator():
    yield 1
    yield 2
    yield 3

gen = simple_generator()
```

To summarise, we can create a Generator type from any of a Generator expression or unintialized/initialized function generator (including lambda functions) so long as they meet the aforementioned assumptions.

i.e.
```python
## as seen ##
Generator(simple_generator())
Generator(simple_generator)
## also works ##
Generator((i for i in range(3))) ## generator expression
```

Once initialized, we can then use it exactly how we normally expect it to work ideally. The Generator type is essentially a cpython generator imitation with the design purpose to be more accessible to users. Therefore, ideally, when it's working it should be identical in expected output to that of a cpython builtin generator and its methods at a high level except with additional accessibilities to further use cases. The further use cases are likely the main appeal of this software design to its users since this includes shallow and deep copying, pickling, and class extensions or other customisations.

i.e. to copy a generator use the copy method for shorthand use:

```python
gen = Generator(simple_generator)
## deepcopy ##
gen_copy = gen.copy()
## shallowcopy (deep=False) ##
gen_copy = gen.copy(False)
```
but you can use the deepcopy and copy functions from the copy module as well since the required dunder methods are implemented e.g. \_\_deepcopy\_\_ and \_\_copy\_\_.

i.e. to pickle and unpickle a generator:

```python
import pickle

gen = Generator(simple_generator)

with open("tests/data/test.pkl", "wb") as file:
    pickle.dump(gen, file)

with open("tests/data/test.pkl", "rb") as file:
    ## they should be identical in terms of the attrs we care about ##
    ## but the state_generator will be deleted (it'll intialize on unpickling) ##
    new_gen = pickle.load(file)
```

## Internals

Instances of ```Generator``` when initialized with a generator will have an ```_internals``` protected variable used by the generator to initialize the frame and to store variables away from the user while it's running. You can access this via ```._internals``` or via ```locals()[".internals"]``` inside your function generator to view the separately stored variables.

Note: the internal variables ```.send, .frame, .self``` will be available during state execution but will be removed on ```Generator._update``` since these are not needed after execution and ```.frame``` and ```.self``` interfere with copying/pickling.


# TODO

### Finish writing tests for:

source_processing:

  - unpack + clean_source_lines recent issues + fixes (bracket issues) (indentation of unpacked lines, closing up of brackets, and bracketed (open brackets) expressions, exceptions, ExceptionGroups, nested exceptions) -- need to fix newlines and comments handling

### Review for testing:

  clean_source_lines:
  
- collect_lambda needs checking
- decorators needs checking
- value yields e.g. decorators/functions/ternary
- loops

check block_adjust

version specific:

- in python 3.14 t-strings were added (treat as f-strings on unpacking)
- in python 3.12 you can arbitarily do nested f-strings but in earlier versions you cannot (update the nesting checker in the string_collectors)
- in python 3.14 exceptions don't need brackets

### Figure out later:
  Initialized Generators:
  - lineno for initialized generators needs checking
  - check the lineno from unpacking for initialized generators
    - check that all unpacked lines are indented where necessary and indentation of future lines must also be considered

    Additional notes on this:
    will need to create an instruction index linetable. Needed to know where to start for initialized
    generators. Though will not know what the prior send values are so will have to run the unpacked
    lines regardless of what the prior send values are or None if there are no prior send values or these
    are not retrievable.
    i.e.
    e.g. line -> instruction index -> unpacked line range
    ```python
    instr_linetable = {
        1: { # key = lineno -> value = dict of # key = instruction index -> value = range in source code
            0: [0,3],
            3: [12,23]
        }
    }
    ```
  - fix and/or add lineno adjust. Then use this for compound statements tracking
  - try to implement ag_await for AsyncGenerator if possible (then test this)
  - enhance code comparisons for source_code_from_comparison for better extraction

  utils:
  - test utils.cli_getsource
  - determine the initial lineno given encapsulated yield and the send values for initialized generators
    - test_lambda_expr in test_custom_generator for encapsulated yields

  generators:
  - test_lambda_expr in test_custom_generator for encapsulated yields
