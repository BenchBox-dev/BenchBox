<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Design & Architecture

```{tags} contributor
```

How BenchBox works internally.

## Contents

### [Architecture Design](architecture.md)
System components and design patterns.

### [Project Structure](structure.md)
Code organization and directories.

##  Design Principles

**Self-contained** - No external dependencies.

**Modular** - Easy to extend and maintain.

**Fast** - Built for performance.

**Cross-database** - Works with any SQL database.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    BenchBox Architecture                    │
├─────────────────────────────────────────────────────────────┤
│  User Interface Layer                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │    TPCH     │ │   TPCDS     │ │ JoinOrder   │    ...    │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  Core Framework Layer                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ BaseBench   │ │ QueryMgr    │ │ DataGen     │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ SQL Trans   │ │   Caching   │ │ File I/O    │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## Component Overview

**Core Framework**
- BaseBenchmark - Base class for all benchmarks
- QueryManager - SQL query storage
- DataGenerator - Data generation
- Schema - Database schemas

**Benchmarks**
- TPC-H, TPC-DS, Join Order, Primitives
- Custom benchmark support

**Infrastructure**
- SQL Translation - Cross-dialect support
- Caching - Performance optimization
- File I/O - Data management

## Design Patterns

**Strategy Pattern** - Different data generation algorithms.

**Factory Pattern** - Consistent benchmark creation.

**Template Method** - Standardized execution workflow.

##  Getting Started

1. Read [Architecture Design](architecture.md)
2. Review [Project Structure](structure.md)

```{toctree}
:maxdepth: 1
:caption: Design Docs
:hidden:

architecture
structure
```
