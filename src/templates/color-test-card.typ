// color-test-card.typ — Color swatch test card for reMarkable Kaleido 3
// Render: typst compile src/templates/color-test-card.typ output.pdf

#set page(margin: 1.5cm, numbering: "1")
#set text(font: "New Computer Modern", size: 10pt)

#align(center)[#text(size: 18pt, weight: "bold")[Kaleido 3 Color Test Card]]
#v(0.3em)
#align(center)[#text(size: 9pt, fill: rgb("#666666"))[View on Paper Pro. Note which colors are visible, washed out, or indistinguishable.]]
#v(1em)

#let swatch(color, label) = {
  box(width: 2.2cm)[
    #stack(dir: ttb, spacing: 2pt,
      rect(width: 2cm, height: 1cm, fill: rgb(color), stroke: 0.5pt + rgb("#999999")),
      align(center)[#text(size: 7pt)[#color]],
      align(center)[#text(size: 6.5pt, fill: rgb("#666666"))[#label]],
    )
  ]
}

#let section(title) = {
  v(0.6em)
  text(size: 12pt, weight: "bold")[#title]
  v(0.3em)
}

#section[Heading Colors (Blues)]
#grid(columns: 6, gutter: 8pt,
  swatch("#0000AA", "dark blue"),
  swatch("#0000CC", "med blue"),
  swatch("#000088", "navy"),
  swatch("#003366", "steel"),
  swatch("#1a1a8a", "deep blue"),
  swatch("#2222AA", "royal"),
)

#section[Code Keywords (Blues)]
#grid(columns: 6, gutter: 8pt,
  swatch("#0000CC", "keyword"),
  swatch("#0033CC", "kw alt1"),
  swatch("#0044AA", "kw alt2"),
  swatch("#0000FF", "pure blue"),
  swatch("#0055BB", "kw alt3"),
  swatch("#2244CC", "kw alt4"),
)

#section[Code Strings (Greens)]
#grid(columns: 6, gutter: 8pt,
  swatch("#006600", "dark green"),
  swatch("#008800", "med green"),
  swatch("#005500", "forest"),
  swatch("#007700", "green"),
  swatch("#336633", "muted grn"),
  swatch("#009900", "bright grn"),
)

#section[Code Comments (Reds/Oranges)]
#grid(columns: 6, gutter: 8pt,
  swatch("#CC3300", "red-orange"),
  swatch("#CC0000", "pure red"),
  swatch("#AA4400", "dark orange"),
  swatch("#BB2200", "deep red"),
  swatch("#993300", "brown-red"),
  swatch("#DD4400", "bright org"),
)

#section[Accents (Teals/Cyans)]
#grid(columns: 6, gutter: 8pt,
  swatch("#006666", "dark teal"),
  swatch("#008888", "med teal"),
  swatch("#005555", "deep teal"),
  swatch("#007777", "teal"),
  swatch("#336666", "muted teal"),
  swatch("#009999", "bright teal"),
)

#section[Warnings (Oranges/Yellows)]
#grid(columns: 6, gutter: 8pt,
  swatch("#CC6600", "orange"),
  swatch("#CC8800", "gold"),
  swatch("#AA5500", "dark amber"),
  swatch("#BB7700", "amber"),
  swatch("#DD9900", "bright gold"),
  swatch("#EEAA00", "yellow"),
)

#section[Saturation Extremes (Gamut Boundary)]
#grid(columns: 6, gutter: 8pt,
  swatch("#FF0000", "red max"),
  swatch("#00FF00", "green max"),
  swatch("#0000FF", "blue max"),
  swatch("#FF6600", "orange max"),
  swatch("#CC00CC", "magenta"),
  swatch("#00CCCC", "cyan"),
)

#v(1em)
#section[Text Readability on Color Backgrounds]
#grid(columns: 3, gutter: 8pt,
  box(width: 5cm)[
    #block(fill: rgb("#E8E8E8"), inset: 6pt, radius: 3pt, width: 100%)[
      #text(size: 9pt)[`code on #E8E8E8`\ gray background]
    ]
  ],
  box(width: 5cm)[
    #block(fill: rgb("#F0F0F0"), inset: 6pt, radius: 3pt, width: 100%)[
      #text(size: 9pt)[`code on #F0F0F0`\ lighter gray]
    ]
  ],
  box(width: 5cm)[
    #block(fill: rgb("#DDEEFF"), inset: 6pt, radius: 3pt, width: 100%)[
      #text(size: 9pt)[`code on #DDEEFF`\ blue tint]
    ]
  ],
)
