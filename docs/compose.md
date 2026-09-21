# Compose

[`.XCompose`](../dotfiles/.XCompose) defines sequences for Greek letters, mathematical symbols, subscripts, and accented letters. `install.py` copies it to `~/.XCompose`. Both [desktop configurations](desktop.md) assign Right Alt as Compose: Sway uses `compose:ralt`, while i3 runs an `xmodmap` command assigning `Multi_key` to `Alt_R`.

Press and release Right Alt, then type the listed keys in sequence. Spaces in the tables separate keystrokes; do not type those spaces. Uppercase letters and punctuation mean the actual character, using Shift where needed. These are the mappings declared in the file; loading and rendering depend on the application's Compose support and font.

## Greek letters

Lowercase Greek sequences start with `g`.

| Keys after Compose | Result | Keys after Compose | Result |
| :--- | :--- | :--- | :--- |
| `g a` | α | `g b` | β |
| `g g` | γ | `g d` | δ |
| `g 3` | ϵ | `g v e` | ε |
| `g z` | ζ | `g e t` | η |
| `g h` | θ | `g i` | ι |
| `g k` | κ | `g l` | λ |
| `g m` | μ | `g n` | ν |
| `g x` | ξ | `g p` | π |
| `g r` | ρ | `g s` | σ |
| `g t` | τ | `g f` | ϕ |
| `g c` | χ | `g u` | ψ |
| `g o` | ω | | |

The uppercase mappings are `g G` → Γ, `g D` → Δ, `g H` → Θ, `g L` → Λ, `g X` → Ξ, `g P` → Π, `g S` → Σ, `g F` → Φ, `g U` → Ψ, and `g O` → Ω.

## Accents, subscripts, and alphabets

| Keys after Compose | Example result | Family |
| :--- | :--- | :--- |
| `- a` | a̅ | Latin overbar |
| `g - a` | α̅ | Greek overbar |
| `^ a` | â | Latin circumflex |
| `g ^ a` | α̂ | Greek circumflex |
| `. a` | ȧ | Single dot |
| `" a` | ä | Double dot |
| `_ a` | ₐ | Subscript |
| `b a` | 𝐚 | Mathematical bold lowercase |
| `B R` | ℝ | Double-struck uppercase |

The supported subscript letters are `a e h i j k l m n o p r s t u v x`. Bold lowercase and double-struck uppercase cover the Latin alphabet. Consult the source for the exact accented-letter mappings; dead-key alternatives are only defined for selected entries. Some outputs contain a base character plus a combining mark.

The Latin circumflex entry for `o` is currently spelled `<asci_icircum>` in the source, unlike the `<asciicircum>` used elsewhere. Treat `Compose ^ o` as a configuration issue to investigate if it fails; this documentation does not change that entry.

## Mathematical symbols

These sequences start with `m` after Compose.

| Keys after Compose | Result | Keys after Compose | Result |
| :--- | :--- | :--- | :--- |
| `m n e` | ≠ | `m a p` | ≈ |
| `m l e` | ≤ | `m g e` | ≥ |
| `m i n` | ∈ | `m ! i n` | ∉ |
| `m n i` | ∋ | `m ! n i` | ∌ |
| `m s q` | √ | `m c r` | ∛ |
| `m c d` | ⋅ | `m t` | × |
| `m / /` | ÷ | `m s i m` | ~ |
| `m s s` | ⊆ | `m ! s s` | ⊈ |
| `m p s s` | ⊊ | `m c a p` | ∩ |
| `m c u p` | ∪ | `m m t` | ↦ |
| `m r a` | → | `m l a` | ← |
| `m i m p` | ⟹ | `m i m b` | ⟸ |
| `m i f f` | ⟺ | `m n b l` | ∇ |
| `m d` | ∂ | `m l n g` | ⟨ |
| `m r n g` | ⟩ | `m p m` | ± |
| `m p t` | ∝ | `m o t` | ⊗ |
| `m o d` | ⨀ | `m e q` | ≡ |

The file also includes the locale's system Compose definitions through `include "%L"`. If a sequence fails, check the active desktop's Compose-key assignment, the application's input method, and whether it loaded the updated file. Use [dotfile syncing](dotfiles.md) to retain intentional local changes.
