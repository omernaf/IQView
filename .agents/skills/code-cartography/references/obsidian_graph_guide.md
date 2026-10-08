# Obsidian Graph View & Canvas Cartography Guide

This document provides visual customization guidelines and Graph View configuration for exploring IQView's codebase in Obsidian.

---

## 1. Graph View Visualization Settings

When opening the `cartography/` folder in Obsidian:

### 1.1 Color Groups (`Graph View -> Groups`)
Add the following queries to colorize architectural domains:
- `tag:#code/moc` $\rightarrow$ `#9b5de5` (Purple: Maps of Content / Hubs)
- `tag:#code/ui/view` $\rightarrow$ `#00bbf9` (Sky Blue: Visual plot canvases and dialogs)
- `tag:#code/ui/mixin` $\rightarrow$ `#00f5d4` (Teal: Main window composite mixins)
- `tag:#code/dsp` $\rightarrow$ `#52b788` (Green: Pure DSP routines, transforms, and math)
- `tag:#code/plugin` $\rightarrow$ `#f15bb5` (Pink: Plugin system, contexts, chains, and overlays)
- `tag:#code/io` $\rightarrow$ `#fee440` (Gold: Binary loaders, audio, and hardware parsers)
- `tag:#code/flow` $\rightarrow$ `#f72585` (Coral Red: End-to-end signal execution paths)

### 1.2 Display Filters (`Graph View -> Filters`)
- Enable **Tags**: Shows tag nodes in the network.
- Enable **Attachments**: Uncheck (keep graph focused on markdown nodes).
- Enable **Existing files only**: Uncheck if you want to see prospective / planned modules.

### 1.3 Forces (`Graph View -> Forces`)
- **Center force**: `0.4`
- **Repel force**: `12.0`
- **Link force**: `1.2`
- **Link distance**: `150`

---

## 2. Note Authoring Conventions

1. **Title Alignment**: Keep note filenames identical to the primary `# Title` in the note.
2. **Double-Bracket Linking**: Always use `[[Note Name]]` or `[[Note Name|Alias]]`.
3. **Mermaid Blocks**: Ensure Mermaid blocks use `graph TD` or `sequenceDiagram` for clean native rendering in Obsidian reading view.
4. **MOC Registration**: When adding a new note, always register its link in the corresponding domain MOC (`MOC - ...`).
