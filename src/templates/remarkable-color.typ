// remarkable-color.typ — Pandoc typst template for Paper Pro Kaleido 3
// Gruvbox LIGHT palette — darker accents designed for white/light backgrounds
// Body: New Computer Modern 11pt, Code: JetBrains Mono 9pt
//
// Gruvbox Light accents (high contrast on white e-ink):
//   Red:    #9D0006   Green:  #79740E   Yellow: #B57614
//   Blue:   #076678   Purple: #8F3F71   Orange: #AF3A03
//   Gray:   #928374   FG:     #3C3836

#let gruvbox-red = rgb("#9D0006")
#let gruvbox-green = rgb("#79740E")
#let gruvbox-yellow = rgb("#B57614")
#let gruvbox-blue = rgb("#076678")
#let gruvbox-purple = rgb("#8F3F71")
#let gruvbox-orange = rgb("#AF3A03")
#let gruvbox-gray = rgb("#928374")
#let gruvbox-fg = rgb("#3C3836")
#let code-bg = rgb("#E8E8E8")

#let blockquote(body) = [
  #block(
    stroke: (left: 4pt + gruvbox-orange),
    inset: (left: 10pt, top: 6pt, bottom: 6pt, right: 10pt),
    above: 1em,
    below: 1em,
  )[#set text(size: 0.92em, style: "italic"); #body]
]

#let horizontalrule = [
  #line(length: 100%, stroke: 0.5pt + rgb("#999999"))
]

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

#let conf(
  title: none,
  authors: none,
  date: none,
  abstract: none,
  cols: 1,
  margin: (x: 2cm, y: 2cm),
  paper: "a4",
  lang: "en",
  region: "US",
  font: (),
  fontsize: 11pt,
  sectionnumbering: none,
  doc,
) = {
  set page(
    paper: paper,
    margin: margin,
    numbering: "1",
    number-align: center,
  )
  set par(justify: true)
  set text(
    lang: lang,
    region: region,
    font: if font == () { ("New Computer Modern",) } else { font },
    size: fontsize,
  )
  set heading(numbering: sectionnumbering)

  // Heading styles — Gruvbox Light accents, bold, clear hierarchy
  show heading.where(level: 1): it => {
    set text(size: 18pt, weight: "bold", fill: gruvbox-red)
    block(above: 1.4em, below: 0.6em)[#it.body]
  }
  show heading.where(level: 2): it => {
    set text(size: 14pt, weight: "bold", fill: gruvbox-blue)
    block(above: 1.1em, below: 0.5em)[#it.body]
  }
  show heading.where(level: 3): it => {
    set text(size: 12pt, weight: "bold", fill: gruvbox-green)
    block(above: 0.9em, below: 0.4em)[#it.body]
  }

  // Code blocks — JetBrains Mono on gray, with Typst's built-in highlighting
  show raw.where(block: true): it => {
    block(
      fill: code-bg,
      stroke: 0.5pt + rgb("#AAAAAA"),
      inset: 8pt,
      radius: 4pt,
      width: 100%,
      above: 1em,
      below: 1em,
    )[#set text(font: ("JetBrains Mono", "DejaVu Sans Mono"), size: 9pt); #it]
  }

  // Inline code — JetBrains Mono with gray background
  show raw.where(block: false): it => {
    box(
      fill: code-bg,
      inset: (x: 3pt, y: 1.5pt),
      radius: 2pt,
    )[#set text(font: ("JetBrains Mono", "DejaVu Sans Mono"), size: 0.85em); #it]
  }

  // Tables — booktabs style: thick top/bottom/header rules, thin row rules, no vertical
  show table.cell.where(y: 0): set text(weight: "bold")
  set table(
    stroke: (x, y) => (
      left: none,
      right: none,
      top: if y <= 1 { 1.5pt + black } else { 0.5pt + rgb("#999999") },
      bottom: if y == 0 { 1.5pt + black } else { 0.5pt + rgb("#999999") },
    ),
  )

  // Strong text — near-black for readability (wikilinks render as bold)
  show strong: set text(fill: gruvbox-fg)

  // Title
  if title != none {
    align(center)[#block(inset: (bottom: 1em))[
      #text(weight: "bold", size: 1.5em, fill: gruvbox-blue)[#title]
    ]]
  }

  if authors != none {
    let count = authors.len()
    let ncols = calc.min(count, 3)
    grid(
      columns: (1fr,) * ncols,
      row-gutter: 1.5em,
      ..authors.map(author =>
        align(center)[
          #author.name \
          #author.affiliation \
          #author.email
        ]
      )
    )
  }

  if date != none {
    align(center)[#block(inset: 1em)[#date]]
  }

  if abstract != none {
    block(inset: 2em)[
      #text(weight: "semibold")[Abstract] #h(1em) #abstract
    ]
  }

  if cols == 1 {
    doc
  } else {
    columns(cols, doc)
  }
}

#show: doc => conf(
$if(title)$
  title: [$title$],
$endif$
$if(author)$
  authors: (
$for(author)$
$if(author.name)$
    ( name: [$author.name$],
      affiliation: [$author.affiliation$],
      email: [$author.email$] ),
$else$
    ( name: [$author$],
      affiliation: [],
      email: [] ),
$endif$
$endfor$
    ),
$endif$
$if(date)$
  date: [$date$],
$endif$
$if(lang)$
  lang: "$lang$",
$endif$
$if(region)$
  region: "$region$",
$endif$
$if(abstract)$
  abstract: [$abstract$],
$endif$
$if(margin)$
  margin: ($for(margin/pairs)$$margin.key$: $margin.value$,$endfor$),
$endif$
$if(papersize)$
  paper: "$papersize$",
$endif$
$if(mainfont)$
  font: ("$mainfont$",),
$endif$
$if(fontsize)$
  fontsize: $fontsize$,
$endif$
$if(section-numbering)$
  sectionnumbering: "$section-numbering$",
$endif$
  cols: $if(columns)$$columns$$else$1$endif$,
  doc,
)

$for(header-includes)$
$header-includes$

$endfor$
$for(include-before)$
$include-before$

$endfor$
$if(toc)$
#outline(
  title: auto,
  depth: none
);
$endif$

$body$

$for(include-after)$

$include-after$
$endfor$
