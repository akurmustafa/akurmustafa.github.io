![clock_header.jpg](images/clock_header.jpg)
# Query Optimization - Filter Pushdown

## Introduction
In this blog post, we will talk about Filter Pushdown optimization to generate better plans. However, before reading this blog post I recommend reading [part 1](https://akurmustafa.github.io/blogs/query_optimization_introduction/query_optimization_introduction.html) where 
- we discussed the query optimization in general.
- we established pre-requiste concepts for subsequent stages.

In this blog post, I assume reader is familiar with `SQL` queries, `LogicalPlan`, `PhysicalPlan`. Also, I use [Apache Datafusion](https://datafusion.apache.org/) to execute queries and to generate plans. However, similar concepts apply to other sytems. 

In query optimization, our aim is to generate the plan
- which execute fastest
- which minimizes the data transfer between operators

Please note that, these properties are mostly correlated but doesn't imply the other. Hence, the best plan in one sense might be different from the best plan in another sense. Hence, there is no globally "the most optimum" plan for most of the cases.

## Motivating Example
Filter Pushdown is helpful in minimizing the data transfer between operators. Let's see the difference Filter Pushdown can make with an example.

Assume we have following table
```sql
CREATE TABLE IF NOT EXISTS student_table(
    id INT, 
    name VARCHAR, 
    surname VARCHAR, 
    major VARCHAR, 
    country VARCHAR
) AS VALUES
    (100, 'Camille', 'Facio', 'CS', 'ITA'), 
    (101, 'Jack', 'Hu', 'CS', 'US'), 
    (102, 'Steven', 'Smith', 'Mathematics', 'UK'),
    (103, 'Mustafa', 'Demir', 'Mathematics', 'TUR'), 
    (104, 'Ekaterina', 'Mihailov', 'Physics', 'RUS'),
    (105, 'Enrico', 'Bellucci', 'CS', 'ITA'), 
    (106, 'Gerard', 'Depardieu', 'Mathematics', 'FR');
```
Consider following query which executes on this table:
```sql
SELECT major, ARRAY_AGG(DISTINCT country)
FROM student_table
GROUP BY major
HAVING  major = 'CS';
```
The above query collects the different countries that students in the CS department are from. A naive planner would produce following plan for the query above
### Naive Plan
```sql
+--------------+----------------------------------------------------------------------------------------------------+
| plan_type    | plan                                                                                               |
+--------------+----------------------------------------------------------------------------------------------------+
| logical_plan | Projection: student_table.major, ARRAY_AGG(alias1) AS ARRAY_AGG(DISTINCT student_table.country)    |
|              |   Filter: student_table.major = Utf8("CS")                                                         | 
|              |     Aggregate: groupBy=[[student_table.major]], aggr=[[ARRAY_AGG(DISTINCT student_table.country)]] |
|              |       TableScan: student_table projection=[major, country]                                         |
+--------------+----------------------------------------------------------------------------------------------------+
```
However, we do not need to do complex aggregation (`ARRAY_AGG(DISTINCT)`) for each department. The user is only interested in to the `CS` department. Hence, It is enough to do the aggregation for just `CS` department. Hence, we could have used the following plan also for the same task.
### Optimized Plan
```sql
+--------------+--------------------------------------------------------------------------------------------------+
| plan_type    | plan                                                                                             |
+--------------+--------------------------------------------------------------------------------------------------+
| logical_plan | Projection: student_table.major, ARRAY_AGG(alias1) AS ARRAY_AGG(DISTINCT student_table.country)  |
|              |   Aggregate: groupBy=[[student_table.major]], aggr=[[ARRAY_AGG(DISTINCT student_table.country)]] |
|              |     Filter: student_table.major = Utf8("CS")                                                     |
|              |       TableScan: student_table projection=[major, country]                                       |
+--------------+--------------------------------------------------------------------------------------------------+
```
where filtering is done immediately after source. Please note that, both plans are same in terms of end result. They both produce following correct result
```
+-------+-------------------------------------------+
| major | ARRAY_AGG(DISTINCT student_table.country) |
+-------+-------------------------------------------+
| CS    | [ITA, US]                                 |
+-------+-------------------------------------------+

```

Let's quantify the complexity of each plan above to compare their efficieny. For doing so, we assume following properties hold:
- Each operator has a linear complexity `k*n_input_rows`, where `k` is operator specific constant.

To quantify complexity assume following statistics are true for the source (Please note that these assumptions doesn't hold for the example source table given):
- Source table has `N` rows.
- There are `M` distinct `major` columns, with equal group sizes (e.g. each distinct `major` group consists of `N/M` rows).

With these assumptions, complexity for the [naive plan](#naive-plan) would be

| Operator Name | #rows received  | #rows emitted | k (complexity) |
| --- | --- | --- | --- |
| Table Scan | N | N | 1 |
| Aggregate | N | N/M| 4 |
| Filter | N/M | 1 | 1 |
| Projection | 1 | 1 | 1 |

which has the total complexity of `5 * N + N/M + 1`. Corresponding complexity table for [optimized plan](#optimized-plan) is

| Operator Name | #rows received  | #rows emitted | k (complexity) |
| --- | --- | --- | --- |
| Table Scan | N | N | 1 |
| Filter | N | N/M | 1 |
| Aggregate | N/M | 1| 4 |
| Projection | 1 | 1 | 1 |

which has the total complexity of `2 * N + 4 * N/M + 1`.
As can be seen, for this example. Pushing the filter down is helpful, with given assumptions. 

## Formal Analysis
Let's examine more formally the conditions for when pushing down the filter makes sense. Pushing down the filter can be thought as: Converting following stage
```sql
Filter: <filter conditions>
  Operator
```
in a plan, into stage below
```sql
Operator
  Filter: <filter conditions>
```
To be able to do this conversion, following conditions should hold.
**1.** All of the columns filter expression refers, should be present at the input of the filter.
**2.** Both of these stages should be guaranteed to generate same result.

Otherwise, conversion will produce an invalid plan. 

**Condition 1** holds as long as filter doesn't refer any expression `Operator` generates. As an example 
```sql
Filter: a = 2
  Projection (a, b)
```
can be converted to 
```sql
Projection (a, b)
  Filter: a = 2
```
However, 
```sql
Filter: c = 2
  Projection (a, b, a + b as c)
```
cannot be converted to 
```sql
Projection (a, b, a + b as c)
  Filter: c = 2
```
Since, `Column: c` is not available for `Filter` without `Projection`.

**Condition 2** holds as long as `Filter` and `Operator` are commutative. Most of the operators I know of have this property. However, for `Limit` this property doesn't hold (First N entries after applying filter and applying filter to the first N entries are different). Hence for `Limit` operation, filter shouldn't be pushed down through limit.

When these conditions hold, we can analyze whether this conversion is beneficial or not. To do so, assume:
- Filter condition removes rows with probability: `p`.
- `Operator` generates `r * N` rows at its output, given it receives `N` rows.
- Per row complexity constant for the `Operator` is `r1 * k` where `k` is the per row complexity constant for `Filter`.

Complexity table for the `Stage 1` (the version where `Filter` is above of the `Operator`) is:
| Operator Name | #rows received  | #rows emitted | k (complexity) |
| --- | --- | --- | --- |
| Operator | N | r * N | r1 * k |
| Filter | r*N | N2 * (1-p) | k |

This table has the complexity `N * r1 * k + r * N * k` which can be written as `N * k * (r1 + r)`.

`Stage 2`, where filter pushed down below `Operator` has following complexity table
| Operator Name | #rows received  | #rows emitted | k (complexity) |
| --- | --- | --- | --- |
| Filter | N | N * (1-p) | k |
| Operator | N * (1-p) | r * N * (1-p) | r1 * k |

Overall complexity for this stage is:
`N * k + N * (1 - p) * r1 * k` which can be written as `N * k  * (1 + (1 - p) * r1)`.

Comparing these two complexities, we can conclude that as long as 
`1 - r <= p * r1` holds, pushing down the filter makes sense. 
With this condition in hand, let's consider some common cases
## Case 1 `r = 1`.
`r = 1` means that number of rows received and enitted by the operator is same. For these operators, condition for filter pushdown turns into `0 <= p * r1`. This condition says that as long as `Filter` condition removes out something (If we are sure that filter doesn't prune anything. We should remove filter from the plan. This is another optimization). We should pushdown filter through this operator. Hence, pushing down the `Filter` through operators where `r = 1` such as
- `Projection`
- `Sort`
- `Window`

is beneficial.

## Case 2 `r > 1`.
`r > 1` means that number of rows emitted by the operator is larger than number of rows received by the operator. For these operators, condition for filter pushdown `1 - r <= p * r1` always holds true. Hence, pushing down the `Filter` through operators where `r > 1` such as 
- `Union All`
- `CrossJoin`

is beneficial.

## Case 3 `r < 1`.
`r < 1` means that number of rows emitted by the operator is smaller than number of rows received by the operator. For these operators, condition for filter pushdown `1 - r <= p * r1` depends on the value of `p`, `r1`, and `r`. However, for common valid cases, where `p` is not too close to `0` (e.g. filter condition removes non-negligible part of the rows) and `r1` is much larger than `1` (e.g. Complexity constant for the `Operator` is much larger than that of `Filter`.). We can conclude that, pushing down the filter is helpful. Hence, as a good rule of thumb pushing down the `Filter` through operators
- `Aggregate`
- `Join` (`r` value for `Join` might be larger than 1 also.)

is beneficial.

### Conclusion
In this blog post, we have analyzed the conditions when pushing down the filter during planning is beneficial. Filter should be pushed down through an operator, when following conditions hold
- All of the columns filter expression refers, should be present at the input of the filter.
- `Filter` + `Operator` stage and `Operator` + `Filter` stage should generate same results (They should be commutative).
- Pushing down the filter would indeed be more efficient in terms of execution.

We have seen that, last condition is `true` for most of the cases. Hence, as a good rule of thumb `Filter` operation should be close to the source as much as possible.

### References

1 - [Apache Datafusion Documentation](https://arrow.apache.org/datafusion/)