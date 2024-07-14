![clock_header.jpg](images/balance_order.jpg)
# Query Optimization - When Ordering Requirement is Satisfied?

## Introduction
In following blog post, we will talk about order based optimizations to generate better plans which are critical for generating streaming friendly pipelines. Before doing so, I think it is worth to analyze how to determine whether an ordering requirement is satisfied by the existing ordering. This analysis is pre-condition for order based optimizations and also much more complex than one thinks initially.

However, before reading this blog post I recommend reading the [introduction](https://akurmustafa.github.io/blogs/query_optimization_introduction/query_optimization_introduction.html) where 
- we discussed the query optimization in general.
- we established pre-requiste concepts for subsequent stages.

If you are familiar with the concepts above, fell free to continue.

## Example
Some of the operators in the physical plan require its input data to be ordered. If its requirement is not satisfied we may insert a `Sort` operator to meet its requirement. If requirement is already satisfied, we may continue with current plan without modification. 

If we don't insert a Sort operator where we should (because of incorrect analysis), the result generated will be wrong. Alternatively, if we insert a Sort operator where we don't need to, the result generated will be correct but inefficient. Hence, it is important to determine whether an ordering requirement by the operator is satisfied by the data at its input. Doing this analysis wrongly or ineffectively may cause planner to generate invalid or sub-optimal plans.

As an example, consider `SortPreservingMerge: required_ordering: [<expr> <DIR>, ..]` operator. This operator takes data from multiple input partitions, then merges these data into single partition according to specied ordering. For this operator to work as desired each of its input should satisfy the required ordering by the operator. Otherwise, resulting data wouldn't have correct ordering.

If the `SortPreservingMerge: [a ASC]` operator merges 2 partitions. Each of its input should satisfy ordering `[a ASC]`. As an example, data from the 1<sup>st</sup> partition would be
| a   |
|-----|
| 1   |
| 3   |
| 5   |

data from the 2<sup>nd</sup> partition would be
| a   |
|-----|
| 2   |
| 4   |
| 6   |

where `SortPreservingMerge` would produce
| a   |
|-----|
| 1   |
| 2   |
| 3   |
| 4   |
| 5   |
| 6   |

by merging these two partitions.

## Test Data
We will use following showcase table as an example. Then we will analyze whether an ordering requirement is satisfied by this table or not (This table can be thought as virtual table between the immediate operators in the physical plan which contains data transferred between them).

| a1 | a2 | c1 | c2| b1| b2| a2_clone | b2_clone |
|---|--- |---|---|---|---|---       | ---      |
|0  |0   | 0 | 1 | 0 | 0 | 0        | 0 |
|0  |1   | 0 | 1 | 0 | 0 | 1        | 0 |
|1  |0   | 0 | 1 | 0 | 1 | 0        | 1 |
|1  |1   | 0 | 1 | 0 | 2 | 1        | 2 |
|1  |2   | 0 | 1 | 1 | 0 | 2        | 0 |
|2  |0   | 0 | 1 | 1 | 1 | 0        | 1 |
|2  |1   | 0 | 1 | 1 | 2 | 1        | 2 |

For this analysis, it useful to keep track of some properties for the table. These properties are
- Constant columns 
- Equivalent column groups 
- Existing orderings of the table.

#### Constant Columns
Constant columns are the columns where each row in the column is same with another. (Although, constant columns might seem weird for a table to have. These columns can arise after `Filter`, `Join` operations). In our example table `Column: c1` and `Column: c2` have this property. We can store constants as following vector `[c1, c2]` for this table.

#### Equivalent Column Groups
Equivalent Column Groups are columns that have same value. These columns can be thought as cloned version of one another. Similar to constant columns, these columns may arise after `Filter`, `Join`, `Projection` operations. In our example table, Columns: `a2`, `a2_clone` and `b2`, `b2_clone` constructs 2 equivalance groups, where each group contains 2 columns. (A group may contain more than 2 entry also). For our table, we can store equivalent columns groups as nested vector: `[[a2, a2_clone], [b2, b2_clone]]` where inner vector consists of the columns inside the equivalent group. 

#### Existing Orderings of the Table.
Existing Orderings are the valid orderings that table satisfies. However, there are many possible options for valid ordering. Let's enlist some of them
`[a1 ASC, a2 ASC]`, 
`[a1 ASC]`,
`[a1 ASC, a2_clone ASC]`, 
`[a1 ASC, a2 ASC, c1 ASC]`, 
`[a1 ASC, a2 ASC, c1 DESC]`, 
`[a1 ASC, c1 ASC, a2 ASC]`, 
`[a1 ASC, c1 DESC, a2 ASC]`,
.
.
.

 As can be seen from the above valid orderings. Storing all of the valid orderings is wasteful, and contains lots of redundancy. Some of the problems are
 - Storing prefix of another valid ordering is redundant. If the table satisfies lexicographical ordering `[a1 ASC, a2 ASC]`, it already satisfies ordering `[a1 ASC]` trivially. Hence, once we store `[a1 ASC, a2 ASC]` we do not need to store `[a1 ASC]` seperately.
 - Using all entries in an `EquivalenceGroup` is redundant. If we know that ordering `[a1 ASC, a2 ASC]` is satisfied by the table, table also satisfies `[a1 ASC, a2_clone ASC]` since `a2` and `a2_clone` are equal. Hence, it is enough to use just one `column` (let's say first column) in an equivalence group during the construction of the the valid orderings.
 - Constant columns can be inserted into any place inside valid ordering with arbitrary direction (`ASC`, `DESC`). Hence, If ordering `[a1 ASC, a2 ASC]` is valid, orderings: `[c1 ASC, a1 ASC, a2 ASC]`, `[c1 DESC, a1 ASC, a2 ASC]`, `a1 ASC, c1 ASC, a2 ASC`, .. are all also valid. This is clearly redundant. For this reason, it is better to not use any constant column during existing ordering construction.

In summary, 
- We should only use the longest lexicographical ordering as a valid ordering (shouldn't use any prefix of it)
- Ordering should contain only one column among an equivalence group.
- Existing ordering shouldn't contain any constant column.

Adhering to these principles, valid orderings are `[a1 ASC, a2 ASC]`, `[b1 ASC, b2 ASC]` for the example table above.

Following above procedure, example table has
- `Constant Column`s = `[c1, c2]`
- `Equivalence Column Group`s = `[[a2, a2_clone], [b2, b2_clone]]`
- `Valid Ordering`s = `[[a1 ASC, a2 ASC], [b1 ASC, b2 ASC]]` (where `a2` is used from the `Equivalence Group`=`[a2, a2_clone]` and `b2` is used from the `Equivalence Group`=`[b2, b2_clone]`).

## Analysis to Determine whether Ordering Requirement is Satisfied
Once we contruct `Constant Column`s, `Equivalence Group`s and `Valid Ordering`s for the table we can analyze whether an ordering requirement is satisfied by these properties.

Algorithm for doing so is as follows
- Prune out constant expressions from the ordering requirement.
- Normalize ordering requirement using `Equivalence Group`s (e.g. replace expressions in the `EquivalenceGroup` with first entry in the `EquivalenceGroup`). By this way we guarantee expressions match with representation inside the `Valid Ordering`s.
- De-duplicate expressions in the ordering requirement where first entry is used among duplicated entries.
- Iterate over the resulting expression to check whether current expression matches with any of the leading orderings (e.g. first ordering in a lexicographical ordering) among the existing orderings. If so, remove the leading ordering from corresponding `Valid Ordering` and continue iteration. If not, stop iteration.
- If iteration completes without early exit, ordering is satisfied by existing properties. Otherwise it is not.

To see algorithm in place, let's look at a concrete example: 
Check whether the ordering requirement `[c1 DESC, a1 ASC, b1 ASC, a2_clone ASC, b2 ASC, c2 ASC, a2 DESC]` is satisfied by the example table above where constants are `[c1, c2]`, `Equivalence Group`s are `[[a2, a2_clone], [b2, b2_clone]]` and `Valid Ordering`s are `[[a1 ASC, a2 ASC], [b1 ASC, b2 ASC]]`.

After pruning out constant expressions ordering requirement `[c1 DESC, a1 ASC, b1 ASC, a2_clone ASC, b2 ASC, c2 ASC, a2 ASC]` turns into `[a1 ASC, b1 ASC, a2_clone ASC, b2 ASC, a2 DESC]`.

After normalization, where we convert `Column: a2_clone` into `Column: a2` and `Column: b2_clone` into `Column: b2`. Ordering requirement turns into `[a1 ASC, b1 ASC, a2 ASC, b2 ASC, a2 DESC]`.

After de-duplicating expressions where first encountered entry is kept, requirement turns into `[a1 ASC, b1 ASC, a2 ASC, b2 ASC]` (Please note that during de-duplication direction is not important as long as expressions match).

Now, problem is reduced to whether `Valid Ordering`s `[[a1 ASC, a2 ASC], [b1 ASC, b2 ASC]]` satisfies ordering requirement `[a1 ASC, b1 ASC, a2 ASC, b2 ASC]`.

Then, check whether `a1 ASC` is among the leading orderings of the `Valid Ordering`s available. Leading orderings are `a1 ASC, b1 ASC`. It is so, hence remove `a1 ASC` from the `Valid Ordering`: `[a1 ASC, a2 ASC]`. 
Now, problem is reduced to whether `Valid Ordering`s `[[a2 ASC], [b1 ASC, b2 ASC]]` satisfies ordering requirement `[b1 ASC, a2 ASC, b2 ASC]`.

Then check whether `b1 ASC` is among the leading orderings of the `Valid Ordering`s available. Leading orderings are `a2 ASC, b1 ASC`. It is so, hence remove `b1 ASC` from the `Valid Ordering`: `[b1 ASC, b2 ASC]`. 
Now, problem is reduced to whether `Valid Ordering`s `[[a2 ASC], [b2 ASC]]` satisfies ordering requirement `[a2 ASC, b2 ASC]`.

Then check whether `a2 ASC` is among the leading orderings of the `Valid Ordering`s available. Leading orderings are `a2 ASC, b2 ASC`. It is so, hence remove `a2 ASC` from the `Valid Ordering`: `[a2 ASC]`. 
Now, problem is reduced to whether `Valid Ordering`s `[[b2 ASC]]` satisfies ordering requirement `[b2 ASC]`.

Then check whether `b2 ASC` is among the leading orderings of the `Valid Ordering`s available. Leading orderings are `b2 ASC`. It is so, hence remove `b2 ASC` from the `Valid Ordering`: `[b2 ASC]`. 
Now, problem is reduced to whether `Valid Ordering`s `[]` satisfies ordering requirement `[]`.

Since, we end up with an empty requirement it is trivially satisfied. We deem that ordering requirement `[c1 DESC, a1 ASC, b1 ASC, a2_clone ASC, b2 ASC, c2 ASC, a2 DESC]` is satisfied by the table with properties:
- `Constants`: `[c1, c2]`, 
- `Equivalence Group`s: `[[a2, a2_clone], [b2, b2_clone]]`
- `Valid Ordering`s: `[[a1 ASC, a2 ASC], [b1 ASC, b2 ASC]]`

## Conclusion
In this blog post, we analyzed the conditions when an ordering requirement is satisfied given the properties of a table. This analysis is useful for the sort based optimizations and helps in generating better plans. Doing this analysis prematurely can cause planner to generate wrong or sub-optimal plans. Hence, this analysis is critical component of a Sort Based optimization rule during planning. 

To see my other blog posts use [link](https://akurmustafa.github.io/blog.html)

### References

1 - [Apache Datafusion Documentation](https://arrow.apache.org/datafusion/)
2 - [Lexicographical Order](https://en.wikipedia.org/wiki/Lexicographic_order)
3 - [Datafusion Implementation of this Analysis](https://github.com/apache/datafusion/blob/main/datafusion/physical-expr/src/equivalence/properties.rs)