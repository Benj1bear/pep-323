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

finish testing + review everything

clean_source_lines:

  to be checked:
  - indentation of lines from unpacking in clean_source_lines needs checking
  - test closing up of brackets for both unpack + clean_source_lines
  - collect lambda needs checking
  - decorators needs checking
  - value yields e.g. decorators/functions/ternary
  - loops
  - check the lineno from unpacking for initialized generators
    - check that all unpacked lines are indented where necessary
      and indentation of future lines must also be considered
  - lineno for initialized generators needs checking

check block_adjust

unpack:
- check the line continuation is adjusting correctly
  or consider removing char in " \\" case since it's
  only for formatting

- use look aheads to avoid unnecessary code adjustments


Figure out later:

  source_processing:

- fix extract_function for expr_getsource tests
  - then test it in test_source_processing:
    - test_expr_getsource
    - test_extract_function

- examples of how to use ag_await and then cater for it if relevant

utils:
  - test utils.cli_getsource
- consider determining lineno given encapsulated yield and the send values
  - test_lambda_expr in test_custom_generator for encapsulated yields
