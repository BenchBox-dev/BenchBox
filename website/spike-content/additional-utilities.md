# Additional Utilities

Authored contract page for the API reference, written to the page template in the API reference contract decision.

## `benchbox.utils.scale_factor.format_scale_factor`

<span id="benchbox.utils.scale_factor.format_scale_factor"></span>

Returns the scale-factor token that BenchBox uses in file, directory and schema
names.

**Import:** `from benchbox.utils.scale_factor import format_scale_factor` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | required | The benchmark scale factor. |

### Returns

`str`: `sf` followed by digits.

- **Values of 1 or more:** the value without its decimal point (`10` → `sf10`,
  `1.5` → `sf15`).
- **Values below 1:** `0` followed by the decimal digits (`0.1` → `sf01`,
  `0.01` → `sf001`).
- **Zero, negative integers, NaN and values below 1e-10:** return `sf0`.
- **Negative fractions:** return the same token as their absolute value
  (`-0.5` → `sf05`).

The token is not unique: `1.5` and `15` both return `sf15`.

### Raises

`OverflowError` for infinity.

### Example

```python
from benchbox.utils.scale_factor import format_scale_factor

assert format_scale_factor(1) == "sf1"
assert format_scale_factor(0.01) == "sf001"
assert format_scale_factor(2.25) == "sf225"
```
