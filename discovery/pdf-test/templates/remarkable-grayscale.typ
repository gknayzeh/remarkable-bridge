// remarkable-grayscale.typ — Pandoc typst template for rM2 grayscale e-ink
// High contrast black/gray only — no colors

// Pandoc definitions partial
#let blockquote(body) = [
  #block(
    stroke: (left: 4pt + rgb("#404040")),
    inset: (left: 10pt, top: 6pt, bottom: 6pt, right: 10pt),
    above: 1em,
    below: 1em,
  )[#set text(size: 0.92em, style: "italic"); #body]
]

#let horizontalrule = [
  #line(start: (25%, 0%), end: (75%, 0%))
]

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

// conf function expected by pandoc's typst output
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

  // Heading styles — black, bold, clear hierarchy
  show heading.where(level: 1): it => {
    set text(size: 18pt, weight: "bold")
    block(above: 1.2em, below: 0.6em)[#it.body]
  }
  show heading.where(level: 2): it => {
    set text(size: 14pt, weight: "bold")
    block(above: 1em, below: 0.5em)[#it.body]
  }
  show heading.where(level: 3): it => {
    set text(size: 12pt, weight: "bold")
    block(above: 0.8em, below: 0.4em)[#it.body]
  }

  // Code blocks — monospace on light gray, no syntax color
  show raw.where(block: true): it => {
    block(
      fill: rgb("#E8E8E8"),
      stroke: 0.5pt + rgb("#999999"),
      inset: 8pt,
      radius: 2pt,
      width: 100%,
      above: 1em,
      below: 1em,
    )[#set text(size: 0.85em); #it]
  }

  // Inline code
  show raw.where(block: false): it => {
    box(
      fill: rgb("#E8E8E8"),
      inset: (x: 3pt, y: 1pt),
      radius: 2pt,
    )[#set text(size: 0.9em); #it]
  }

  // Title
  if title != none {
    align(center)[#block(inset: (bottom: 1em))[
      #text(weight: "bold", size: 1.5em)[#title]
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

// Apply conf (pandoc fills in the parameters)
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
