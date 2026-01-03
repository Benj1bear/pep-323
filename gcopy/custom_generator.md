## Documentation for custom_generator

in this file I'll be exploring the library files explaining what the core pipeline of the conceptual process is at a high level and then explaining to a reasonable extent what each function does and how it's related to each other in terms of what goals each achieves at a lower level e.g. one of more nuance.

In general, generators in python are considered single use only and only iterated through not copyable and definitely not picklable. The motivation behind this project was the realization that you can copy a generator and pickle it if a set of assumptions are not violated. If the assumptions hold then we can do a lot of meta analysis or code representation manipulation to get the yield effect and others (e.g. throw, send, close). The crux of the idea is that if the things of the objects make up are copyable/pickleable then what's left in order to make it usable is the need of adjustments of the parts that will need implementation to make up the whole.

## custom_generator.py

This file implements a class called Generator to emulate what a function generator does in cpython.

Note: it's currently not finished yet; see the TODO comment in ```comments.py```.

## approach:

To emulate a generator we essentially evaluate source code on the fly sectioning the source code by its yield statements (shouldn't do inner functions however) and using these sections of the source code as each generators state. Using source code is much easier to manipulate (especially across different versions of cpython) and means all the work to get it working is mostly in initialisation and adjusting the source code per iteration.

There are two parts that make up the process on the whole at a high level that will be explored e.g. initialisation and generation.

# Detailed overview

## code layout

gcopy : 
 - utils.py : utility functions
 - track.py : tracking
 - source_processing.py : cleaning + adjusting + extracting source code
 - custom_generator.py : pickleable / copyable objects

# Running the Generator:

## Assumptions

The idea is actually very simple e.g. emulate what a generator does.

In order to achieve this the following assumptions are assumed to be true for the software design to conceptually work:

1. you can retrieve the correct source code of your generator expression or generator function.

2. There are no compound statements present in the source code of your generator functions that have yields or yield froms and the current lineno if running an initialized generator past one execution shouldn't be on an encapsulation of yields.

This assumption may become somewhat relaxed with the implementation of ```lineno_adjust``` and the use of ```get_instructions```, however, this is not guaranteed to work across all python versions since 3.11 is when python introduced ```CodeType.co_positions``` enabling source code positions with column offsets. In general, using compound statements or stopping on an encapsulation is not recommended when trying to initialize a ```Generator``` instance from a running generator.

Specifically for encapsulations, there's no way to know what values were sent but even if we did there's no way to account for control flow adjust unless we record that too. It's recommended to create a BaseGenerator before and use that since you can stop on encapsulations and retain the state with this object but in the case of regular generators we'd likely need to look into the interpreter frames value stack or otherwise monkey patch caches as much as necessary. Both solutions are very hacky for what is considered a nieche use case that's avoidable if you don't need the assumption that your generator must come from an initialized / already running, cpython generator that had values sent to it.

On the other hand one thing that is possible is assuming the user didn't send any values at all, in which case we can replace all the inlined yields prior to the current execution to ```None```.

3. you can retrieve the last line of execution in relation to your source code i.e. if ```gen``` is your generator then you should be able to go ```gen.gi_frame.f_lineno``` to retrieve this.

4. all required variables in its current state can be retrieved.

i.e. if again ```gen``` is your generator then you should be able to go ```gen.gi_frame.f_locals``` to retrieve the locals.

One problem is that all implicitly defined for loop iterators may not be explicitly located and retrieved from memory.

I.e. how would you retrieve the iterator defined here reliably (bear in mind that you might also have other range iterators in memory as well):

```python
for i in range(3):
    ...
```
This makes determining where in memory ```iter(range(3))``` is more difficult but is maybe possible in further investigations though from some investigating it seems at least naively that it's not possible.

For now this means using our ```track``` function; for ease of use we recommend importing the monkey patches e.g. calling ```patch_iterators(globals())```.

5. Avoid overriding ```locals()[".internals"]``` and gen._internals in your generator (unless there's a particular reason why doing so makes sense).

```locals()[".internals"]``` is assumed to be a reserved namespace for all internally stored variables (i.e. track_iter uses it to store the implicit iterators) and other adjustments needed at execution to help make the Generator instance work on running \_\_next\_\_. 

If it's not being used or some of the keys are unused then yes you can modify it but I would recommend against using it if you don't understand when it needs to be reserved because failure in doing so may see you overriding a variable that breaks expected execution and thus your code won't work as expected. Specifically, overriding any of the variables mentioned in the third bullet point in the last section of this document called **Other notes** when it's used for a current adjustment.

As for gen._internals, this is a dictionary holding important references used in code adjustment:
 - lineno
 - frame
 - jump_positions
 - code
 - yieldfrom
 and others

Therefore, if you modify any one of these (especially the first two), expect the code adjusters not to work and your code not to run as expected.

When these assumptions hold the following conceptual design framework follows:

## initialisation

1. The source code of your generator is retrieved via ```inspect.getsource``` and ```expr_getsource``` for function generators and expressions respectively.

2. standardize the source code retrieved and split it into lines so that it's in a usable format using ```clean_source_lines```. 

e.g. 
- makes sure the indents are correct where using ";" (since they don't have to start with an indentation of 4)

- split on "\n" and ";"

- join up the line continuations i.e. "\ ... " will be skipped

translate certain sections of the source code into a usable format by the generator with ```custom_adjustment```
e.g. 
 - ```yield``` statements are written as returns to give the temporary exiting; this helps with the code adjustments later that gives the continuation.

 - ```yield from``` statements are written as for loops with returns to give the same effect as yields.

 - ```return``` statements are replaced with a custom ```EOF``` exception type (inheriting from ```StopIteration```) of the return value.

 - Definitions e.g. ```def, async def, class, ... = lambda ...``` are left untouched since these are classes/functions of their own.

 - assignment yields e.g. ```...=yield ...``` are adjusted via the ```unpack``` function for capability to receive values sent via the ```Generator.send``` method.

 - Records the start and end ```lineno``` positions for the ```for``` and ```while``` loops for later use when needing to adjust the current source code inside a loop encapsulation. These positions are recorded in the ```Generator._internals["jump_positions"]``` variable. Temporarily, a ```jump_stack``` is also used to later detect the end position and then update this in the jump_position back in ```clean_source_lines```.

Also, value yields are handled via ```clean_source_lines``` and both string collector functions (or ```string_collector_proxy```)  e.g. yields of the form ```(yield ...)``` (yield statement with brackets around it).

There is an efficiency trade off made in the use of ```unpack``` in ```string_collector_proxy``` is that both string collectors will make the assumption that all f-strings imply unpacking which is not necessarily always true but is a kind of blanket argument/safety in case of value yields in f-strings. This is more from an efficiency standpoint of trying to avoid as many linear searches as possible in the sense of double handling (may be further tested).

Value yields are handled by ```unpack``` by inserting new lines into the current source lines as the value yields need to be evaluated prior to usage e.g. value yields yield values but also returns a value (e.g. if you send a value to it via ```Generator.send``` rather than running ```next()``` otherwise its return value is by default ```None```) therefore the idea is to yield the values before (will work the same since the entire line is ran like this e.g. anything before the yield will also need to be saved into the stack since the yield could yield from an i.e. iterable and therefore depends on what line ran before), save their returns into a temporary stack, pop the stack / unpack all the value into its expression.

```unpack``` not only unpacks but unwraps (for recursion or bracketed expressions), and goes through yield adjust for each new line added to ensure that the line is custom adjusted.

Decorators and definitions are also adjusted in case of value yields by saving to an internal variable to preserve them.

Note: If initializing from a generator expression these will be unpacked instead since no yields should be present; lambda functions will also be unpacked but then ran through clean_source_lines after since it can have yields so long as the expression is encapsulating this in brackets (e.g. the lambda expression should've come from a functions scope).

4. initialize the generator ```_internals``` with attributes (should resemble a generators attrs but some are new add ons for better accessibility):
 - code
 - frame
 - running
 - suspended
 - yieldfrom
 - lineno
 - state
 - jump_positions
 - state_generator

Note: I've made the attrs available under ```_internals``` to seperate the familiar api and the attrs used. This also helps with translating the Generator function to ```AsyncGenerator``` since it means only needing to setup the prefix and type as seen in the code:
```python
class AsyncGenerator(Generator):
    _internals={"prefix":"ag_","type":AsyncGeneratorType}
```
So this means the attrs starting with a prefix will be accessible via i.e. ```Generator(FUNC).gi_frame``` but the others only via ```Generator(FUNC)._internals```.

5. The state generator (```Generator()._internals["state_generator"]```) is created via ```Generator.init_states``` setting the state generator as an evaluation loop where with each iteration the code is adjusted by ```Generator._create_state```.

Note: if you are initializing on an uninitialized Generator a ```__call__``` method will be set to the instance since for some reason dynamically changing the ```__call__``` is maybe not possible. Specifically it will be set to a signed version of ```Generator__call__```. Signed so that the signature and binding is the same as your uninitialized generator.

Additionally, if your generator has a closure this will be added as attribute to the ```Generator``` instance. The binding will still work (mentioned later in ```Generator._frame_init```), however, copies will no longer have a binding e.g. I suspect copy/pickle methods automatically remove the ```__closure__``` attribute if it exists on the instance. However, if you want to reinstate the binding to the same or a different closure all you need to do is set a ```__closure__``` attribute manually (and make sure you have a ```__code__``` attribute for ```get_nonlocals```) or use ```Generator._bind(self, closure)``` to bind the current instance (```self```) to the closure.

## Code Adjusting

Adjustments are made with ```get_loops```, and ```Generator._internals``` ```lineno``` and ```source_lines``` to slice the source code to the current ```lineno```, adjust the current control flow, finish the current loop encapsulating the current line (if it has one), and add the remaining loops. 

```get_loops``` gets the loops encapsulating the current line. It does a linear search to check which one.

To illustrate ```get_loops``` it simply tries to identify the following:

(Note: each column is a jump_position with its start and end position identified via '-'; '|' indicates the correct selection)

```
               |  |  |
            -  -  -
        -
        -   -        -
lineno 
          -    -
                     -
          -
                  -
```
e.g. which of the loop positions together encapsulate the current ```lineno```

In ```Generator._create_state``` we can adjust by ```lineno``` because the code is split up into lines and there are no yields present in the function body excluding inner definitions. This should mean that every line is a single execution and therefore no two lines should (by design) show up thereby allowing a clear iteration progression.

Additionally, the ```control_flow_adjust``` function is used to address unreachable code that occurs since we simply slice the source code by a lineno e.g.:

i.e. the following code would not run due to a ```SyntaxError```

```python

    print("hi")
else:
    print("done")
```
Examples such as these are possible because we are simply slicing based on the ```f_lineno``` and trying to exec this.

Lastly the ```loop_adjust``` is responsible for completing the current loop and ```outer_loop_adjust``` for ensuring that all loops have been iterated through correctly under the approach of simply slicing the source code lines.

```python
for i in range(3):
    for j in range(5):
        print(0)
        for k in range(7):
            if True:
            -----------------------------
                print(1)
                continue
            else:
                print("done")
            break
        print(2)
        for k in range(9):
            print(3)
        print(4)
    print(5)
```
should map to (but without the comments + spacing added):
    
```python

#################
## loop_adjust ##
#################

locals()['.continue']=True
for _ in (None,):
    print(1)
    break # continue adjustment
    break # break adjustment
    locals()[".continue"]=False
    break # this break is here by default since the while loop is to help with control flow
## next section ##
if locals()[".continue"]:
    for k in range(7):
        if True:
            print(1)
            continue
        else:
            print("done")
        break

#######################
## outer_loop_adjust ##
#######################

## next section ##
print(2)
for k in range(9):
    print(3)
print(4)
## next section ##
for j in range(5):
    print(0)
    for k in range(7):
        if True:
            print(1)
            continue
        else:
            print("done")
        break
    print(2)
    for k in range(9):
        print(3)
    print(4)
## next section ##
for i in range(3):
    for j in range(5):
        print(0)
        for k in range(7):
            if True:
                print(1)
                continue
            else:
                print("done")
            break
        print(2)
        for k in range(9):
            print(3)
        print(4)
    print(5)
```

It's also important to note that doing such adjustments e.g. ```control_flow_adjust```,  ```loop_adjust```, and ```outer_loop_adjust``` will change the source code and thus the line numbers, therefore, to ensure we can still perform our slicing we need to create a ```linetable``` for determining the current ```lineno``` correctly after each state (e.g. ```Generator()._internals["state"]```) completion.

## Generation

How the ```next()``` (e.g. the ```__next__``` builtin special/magic/dunder method implementation) usages works is to run in order:

 - _frame_init
 - next_state
 - _update

_frame_init is for initialising the function with a code object created from an adjusted version of the current state and the current states local variables. We can also change certain variables i.e. if the generator is a part of a closure the locals will be updated by the closure variable (if it exists) or add exceptions (e.g. ```Generator.throw```) or send values (e.g. ```Generator.send```).

All the identifiers in the states/frames locals needs to be initialized with its value (otherwise the ```locals``` dict doesn't pick up on it); the currentframe is also saved to the internals for updating the current frame on the instance with the one used in the state.

The remaining state is appended to this initialisation header and the code object is created then this is exec'd. Importantly we name the file location of the code object as ```"<Generator>"``` so that the track iter knows which locals to target.

After initialising the function, we call it and this runs through the current state generation function we created called ```next_state```.

If no errors occured the state is updated e.g. ```Generator._internals["frame"]``` is set with the states frame, ```f_locals``` are updated, ```f_back``` is removed, the ```f_lineno``` is adjusted and then retrieved from the linetable, the current loops encapsulating are recorded, and if necessary the state is set to ```None```.

## copying + pickling

So long as the assumptions mentioned under the assumptions section of this document hold and the frame locals are copyable/pickleable then it should be possible to copy/pickle a generator under these conditions.

How copying and pickling is done is via an inheritance (since more than one class made use of the same methods) of the ```Pickler``` class on definition of the ```Generator``` class. Essentially the idea is simple e.g. if you can copy/pickle the attributes that comprise of the objects state then just copy/unpickle these to make up the object since we cannot directly copy/pickle the object.

This ends up being very simple in implementation as for pickling we are effectively running a for loop on a selection or array of attrs that get a ```getattr``` and ```setattr``` applied for ```__getstate__``` and ```__setstate__``` respectively. For copying we are essentially making use of ```__getstate__``` but applying the desired copier to the attribute e.g. ```copy.copy``` or ```copy.deepcopy```.

You should see that I've made a custom ```code``` and ```frame``` class that also inherit the ```Pickler``` class to ensure that these objects are also pickleable since they are by default not allowed to be pickled.


## Other Notes:

  - while loops don't need tracking and indentation is enough as an identifier for tracking. 
    Also, generator expressions use the column offset then this gets converted into indentation based on \_\_init\_\_.

  - yields in comprehension expressions and exec/eval don't occur in python syntax

  - there is a .internal and it has 'EOF', 'args', 'yieldfrom', 'send', 'exec_info', .decorator, 'partial', '.continue', '.i', '.error', and the tracking variables (indents e.g. '.4' etc.)

    at the moment only 'partial', 'exec_info', '.args', and '.send' are initialized with '.send'
    being initialized with 'None' every iteration except when the user sends an argument

  - I've decided that we don't record f_back for each state since if you really need
    to record the states then you should do that separately before/after each state is
    used because it's generally considered better that way, the bigger downside is the
    memory consumption of saving all the states as f_back on frames when really we're
    usually only interested in it running and it's current state. The previous states
    variables should be the current versions and the linenos can be recorded in between
    states easily. The other exploration one could do is rerunning states again but why
    not just copy the generator then (as this software was designed for)? So it seems
    unnecessary to save as f_back.

  - if the \_\_closure\_\_ attribute is available will be added as attribute to the Generator and
    into its f_locals via get_nonlocals but it will mean that though the original generator
    has a binding to a closure the copied generator will be independent of it e.g. removing
    the closure binding and retaining its version in the state it was copied from. You can
    rebind to a closure if you want by setting a \_\_closure\_\_ attribute and \_\_code\_\_ attribute
    manually that will allow _frame_init to rebind to the desired closure or use the ```_bind``` method. This is not the case when calling an uninitialized generator as the user shouldn't be expected to manually bind to a closure after calling; copying/pickling requires manual binding and calling will already bind the copied generator to the original closure. 

  - no reinitializing supported. It's expected that users either have a function that acts
    as a factory pattern or may copy the generator after initializing e.g. cannot use \_\_call\_\_
    on an initialized generator.

  - the name of the actual state generation function will stay as next_state. It doesn't make 
    sense to rename it as the name of the object used to initialize it as what should happen is
    a recursion to create a new generator object and not a recursion on the same state. To 
    do a recursion on the same state would mean to copy the current state and run that which 
    would be running ```locals()[".internals"][".self"].copy()```. 

    Also, by default, next_state is not defined in the next_state frame therefore it will raise an ```UnboundlocalError``` expecting it defined in any of the local, global, or nonlocal scopes.
    
    Recursion is done for us by python via doing an attribute lookup to the globals dict if we're not in a closure. However, if we are in a closure things are more complex because the function is saved in the closure and we don't want that but this causes issues. Essentially we replace this cell from the closure with a generator version copy of the original function and ensure it's own closure has the ```Generator.__call__``` under its name for this problem to resolve itself if the recursions continue to go deeper.
  
  - If your Generator/frame references global variables then these variables are expected by the
    state when it's called to exist. These should be set manually by the user and pickled separately with unpickling done before the generator runs its \_\_next\_\_ method. 
    
    The reason why the responsibility has been delegated to the user is because of any references made or propagating to other references via exec or eval, which would require a more extensive analysis to determine what globals are being required. Even if you did i.e. compile the expressions in exec/eval you still wouldn't be able to account for anything done dynamically e.g. f-strings or other processes during run time. Thus, in order to know what globals you need to save you also need to run the state i.e. copy it, but this would maybe change the globals values and thus it's not clear what an exact approach would be that generalizes. To an extent a get_globals function could be implemented that goes through f_code.co_names (global names) and sieves through to the names that are not builtins but as aforementioned this doesn't account for anything dynamic. Thus, it's up to the user for pickling the globals.

    On the other hand if users don't mind the potentially high memory consumption and assuming all the global objects are all pickleable then it shouldn't be difficult to save the current global scope (e.g. pickling ```globals()```) even if it requires creating a class with a \_\_getstate\_\_ and \_\_setstate\_\_. So it will be considered an option to save the globals if users want this but would be more efficient/effective to manually decide what variables that are a part of the global scope are necessary.

  - if a closure cell is deleted from the originating scope this will raise an error at get_nonlocals
    for the scope using it since the cell no longer exists which is correct. If you delete a nonlocal in the inner scope, python throws an error on compilation and disallows exec/eval to take effect. If you delete a nonlocal in a ```Generator``` state it gets deleted how a regular deletion of a variable would be deleted; which is perhaps unexpected behaviour relative to how it should be.

  - uninitialized Generators will return copies of instantiated ones when called. This is to preserve the decorator functionality and thus acts as a function would. Whereas initialized generators act as objects.

  - the current states full source is available under the Generator instances ```__source__``` attribute after calling ```__next__```.

  - At a high level, ```AsyncGenerator``` differs by the an additional capacity to use the ```await``` keyword that pauses the current execution to wait for the asynchronous function to return first, stopping is done on an exception raised as ```StopAsyncIteration``` instead of ```StopIteration```, and it uses the ```aiter``` and ```anext``` functions rather than ```iter``` and ```next``` respectively; this is also seen/reflected in the dunders with ```__aiter__``` and ```__anext__``` for the asynchronous version.

  i.e. ```async for i in ...:``` will wrap ```...``` in ```aiter``` e.g. performing ```aiter(...)```.

  Additionally, the return types will be coroutines if ```aiter```, ```anext```, and other asynchronous functions are not awaited.

  Async Generators don't have an ```__await__``` method implementation but they do record the object they are currently awaiting i.e.

  - ag_await and cr_await are when you use i.e asyncio.create_task:
    ```python
    import asyncio

    async def some_task():
        await asyncio.sleep(0.1)

    task = asyncio.create_task(some_task())
    ## delay to allow it to start ##
    await asyncio.sleep(0.1)
    print(task._coro.cr_await)
    ```
    This and the fact that you can have i.e.
    ```await (await ... ), await (await ... ), ...```

    Means we'd need to use the unpack function exactly how we would for
    yields but instead of adjusting for yields it would be adjusting
    for awaits (just to know what object is currently being awaited).
    However, this doesn't seem to be the case with asynchronous generators? 
    Therefore, until I figure out how it's used I will leave it out.

    You can't do ```yield from *async iterator*``` because ```yield from``` use ```iter``` when async generators use ```aiter``` and you can't try ```yield from``` in async functions because they're not allowed e.g. causes syntax / compilation error.

    So, in summary, an async generator type should integrate nicely with the current implementation. The only significant adjustments will be utilizing the await keyword in the relevant functions and if desired implementing an ```ag_await``` attribute requiring additional implementation in custom_adjustment and unpack to unpack and/or unwrap awaits.

  - coroutines are now using await/async syntax since 3.8 deprecated asycnio.coroutine that now
  disallows generator based coroutines e.g. only generators and async generators are possible. If this was not the case I suspect it'd be close to working with the current implementation (if it becomes backwards compatible).

  - only need to record the frames globals upon initialization and pickling since these are the only times necessary. There won't be other times where your generator instance transfers into a new global scope that isn't via pickling from what I'm aware of.

  - in the implementation every call to eval/exec made has tried to ensure the targeted scope is correct to be precise for the calls purpose otherwise there will be unbound local errors in some cases.

  - on ```BaseGenerator.__init__()``` the locals are still the same pointers in the original frame and thus instantiating a i.e. ```Generator``` or ```AsyncGenerator``` type will create pointers essentially. To avoid this, deepcopy the generator after instantiation.

  - f-strings are unpacked. We could check if they need to be unpacked however it's likely about the same or worse than being unpacked without checking.

  - Because bytecode changes with python versions the main functions to look out for in terms of
  instability should start likely with the functions found in utils.py: code_setup, code_attrs, similar opcode, and code_cmp. Though, code_setup is likely the only and most unstable of them that needs review per version change.
