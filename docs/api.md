# API reference

The `budgie.core` engine: all of the budgeting and forecast math, with no UI
imports. The front-ends (CLI, TUI, plots, emails) are thin adapters over it.

```{eval-rst}
.. automodule:: budgie.core
```

## Projects and inputs

```{eval-rst}
.. automodule:: budgie.core.workspace

.. automodule:: budgie.core.project

.. automodule:: budgie.core.scaffold

.. automodule:: budgie.core.csvio

.. automodule:: budgie.core.loader

.. automodule:: budgie.core.guide
```

## Forecasting

```{eval-rst}
.. automodule:: budgie.core.calendar

.. automodule:: budgie.core.person

.. automodule:: budgie.core.forecast

.. automodule:: budgie.core.montecarlo

.. automodule:: budgie.core.monthly

.. automodule:: budgie.core.costs

.. automodule:: budgie.core.scenario
```

## Allocations and spend

```{eval-rst}
.. automodule:: budgie.core.allocation

.. automodule:: budgie.core.plan

.. automodule:: budgie.core.solve

.. automodule:: budgie.core.actuals

.. automodule:: budgie.core.eac

.. automodule:: budgie.core.burndown
```

## Budgets and signals

```{eval-rst}
.. automodule:: budgie.core.budget

.. automodule:: budgie.core.signals
```
