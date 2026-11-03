# Color Themes

Consistent color palettes for diagram styling. Apply via `classDef` in every `.mmd` file.

## Default Theme

The standard palette — use unless the user requests a specific theme.

| Role | Fill | Stroke | Text | classDef Name |
| --- | --- | --- | --- | --- |
| Main app / dispatcher | `#FF6B6B` | `#C0392B` | `#fff` | `mainApp` |
| Foundation / core | `#4ECDC4` | `#1ABC9C` | `#333` | `foundation` |
| UI / presentation | `#96CEB4` | `#27AE60` | `#333` | `uiComp` |
| Business logic | `#F7DC6F` | `#F39C12` | `#333` | `bizLogic` |
| Data stores | `#45B7D1` | `#2980B9` | `#fff` | `dataStore` |
| External services | `#BB8FCE` | `#8E44AD` | `#fff` | `external` |
| Tools / utilities | `#85C1E9` | `#2980B9` | `#333` | `tools` |
| Config / cross-cutting | `#E8E8E8` | `#7F8C8D` | `#333` | `config` |

### Copy-Paste classDef Block (Default)

```mermaid
classDef mainApp fill:#FF6B6B,stroke:#C0392B,color:#fff,stroke-width:2px
classDef foundation fill:#4ECDC4,stroke:#1ABC9C,color:#333,stroke-width:2px
classDef uiComp fill:#96CEB4,stroke:#27AE60,color:#333,stroke-width:2px
classDef bizLogic fill:#F7DC6F,stroke:#F39C12,color:#333,stroke-width:2px
classDef dataStore fill:#45B7D1,stroke:#2980B9,color:#fff,stroke-width:2px
classDef external fill:#BB8FCE,stroke:#8E44AD,color:#fff,stroke-width:2px
classDef tools fill:#85C1E9,stroke:#2980B9,color:#333,stroke-width:1px
classDef config fill:#E8E8E8,stroke:#7F8C8D,color:#333,stroke-width:1px
```

## Corporate Blue Theme

Professional/conservative alternative suitable for enterprise documentation.

| Role | Fill | Stroke | Text | classDef Name |
| --- | --- | --- | --- | --- |
| Main app / dispatcher | `#2C3E50` | `#1A252F` | `#fff` | `mainApp` |
| Foundation / core | `#2980B9` | `#1F618D` | `#fff` | `foundation` |
| UI / presentation | `#27AE60` | `#1E8449` | `#fff` | `uiComp` |
| Business logic | `#F39C12` | `#D68910` | `#333` | `bizLogic` |
| Data stores | `#3498DB` | `#2471A3` | `#fff` | `dataStore` |
| External services | `#8E44AD` | `#6C3483` | `#fff` | `external` |
| Tools / utilities | `#5DADE2` | `#2E86C1` | `#333` | `tools` |
| Config / cross-cutting | `#BDC3C7` | `#95A5A6` | `#333` | `config` |

### Copy-Paste classDef Block (Corporate Blue)

```mermaid
classDef mainApp fill:#2C3E50,stroke:#1A252F,color:#fff,stroke-width:2px
classDef foundation fill:#2980B9,stroke:#1F618D,color:#fff,stroke-width:2px
classDef uiComp fill:#27AE60,stroke:#1E8449,color:#fff,stroke-width:2px
classDef bizLogic fill:#F39C12,stroke:#D68910,color:#333,stroke-width:2px
classDef dataStore fill:#3498DB,stroke:#2471A3,color:#fff,stroke-width:2px
classDef external fill:#8E44AD,stroke:#6C3483,color:#fff,stroke-width:2px
classDef tools fill:#5DADE2,stroke:#2E86C1,color:#333,stroke-width:1px
classDef config fill:#BDC3C7,stroke:#95A5A6,color:#333,stroke-width:1px
```

## Dark Theme

For dark-background renders or dark-mode documentation.

| Role | Fill | Stroke | Text | classDef Name |
| --- | --- | --- | --- | --- |
| Main app / dispatcher | `#E74C3C` | `#FF6B6B` | `#fff` | `mainApp` |
| Foundation / core | `#1ABC9C` | `#48C9B0` | `#fff` | `foundation` |
| UI / presentation | `#2ECC71` | `#58D68D` | `#fff` | `uiComp` |
| Business logic | `#F1C40F` | `#F4D03F` | `#333` | `bizLogic` |
| Data stores | `#3498DB` | `#5DADE2` | `#fff` | `dataStore` |
| External services | `#9B59B6` | `#BB8FCE` | `#fff` | `external` |
| Tools / utilities | `#5DADE2` | `#85C1E9` | `#fff` | `tools` |
| Config / cross-cutting | `#566573` | `#808B96` | `#fff` | `config` |

### Copy-Paste classDef Block (Dark)

```mermaid
classDef mainApp fill:#E74C3C,stroke:#FF6B6B,color:#fff,stroke-width:2px
classDef foundation fill:#1ABC9C,stroke:#48C9B0,color:#fff,stroke-width:2px
classDef uiComp fill:#2ECC71,stroke:#58D68D,color:#fff,stroke-width:2px
classDef bizLogic fill:#F1C40F,stroke:#F4D03F,color:#333,stroke-width:2px
classDef dataStore fill:#3498DB,stroke:#5DADE2,color:#fff,stroke-width:2px
classDef external fill:#9B59B6,stroke:#BB8FCE,color:#fff,stroke-width:2px
classDef tools fill:#5DADE2,stroke:#85C1E9,color:#fff,stroke-width:1px
classDef config fill:#566573,stroke:#808B96,color:#fff,stroke-width:1px
```

## Build Pipeline Theme (Specialized)

Additional classDefs for build/deployment diagrams where standard roles don't apply:

```mermaid
classDef source fill:#96CEB4,stroke:#27AE60,color:#333,stroke-width:2px
classDef precomp fill:#BB8FCE,stroke:#8E44AD,color:#fff,stroke-width:2px
classDef compile fill:#F7DC6F,stroke:#F39C12,color:#333,stroke-width:2px
classDef link fill:#FF6B6B,stroke:#C0392B,color:#fff,stroke-width:2px
classDef package fill:#45B7D1,stroke:#2980B9,color:#fff,stroke-width:2px
classDef output fill:#E8E8E8,stroke:#7F8C8D,color:#333,stroke-width:2px
```

## Hierarchy Theme (Specialized)

Additional classDefs for dependency tree diagrams with level-based coloring:

```mermaid
classDef root fill:#FF6B6B,stroke:#C0392B,color:#fff,stroke-width:3px
classDef level1 fill:#F7DC6F,stroke:#F39C12,color:#333,stroke-width:2px
classDef level2 fill:#96CEB4,stroke:#27AE60,color:#333,stroke-width:2px
classDef level3 fill:#85C1E9,stroke:#2980B9,color:#333,stroke-width:1px
classDef leaf fill:#E8E8E8,stroke:#7F8C8D,color:#333,stroke-width:1px
```

## Custom Theme Guidelines

When creating a custom palette:

1. Stroke color should be ~20-30% darker than fill
2. Use `#fff` text on dark fills, `#333` on light fills
3. Use `stroke-width:2px` for primary nodes, `1px` for secondary
4. Test contrast: ensure text is readable at small sizes
5. Keep to 6–8 role colors maximum for cognitive clarity
