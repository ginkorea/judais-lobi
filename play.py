import json, html
from typing import Any

def _compose_svg(primitives: Any) -> str:
    if isinstance(primitives, str):
        try:
            primitives = json.loads(primitives)
        except json.JSONDecodeError:
            raise ValueError("❌ Cannot parse primitives JSON!")

    svg_elements = []
    for primitive in primitives:
        shape = primitive.pop("shape", primitive.pop("type", None))  # <- Fixed here
        if not shape:
            continue  # Skip malformed primitives

        attributes = " ".join(
            f'{key}="{html.escape(str(value))}"' for key, value in primitive.items()
        )

        if shape in {"rect", "circle", "ellipse", "line", "polygon", "path"}:
            element = f"<{shape} {attributes} />"
            svg_elements.append(element)

    svg_block = (
        '<svg width="1000" height="1000" viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(svg_elements) +
        '\n</svg>'
    )

    return svg_block


primitives = [
{
"type": "circle",
"cx": 500,
"cy": 500,
"r": 50,
"fill": "silver"
},
{
"type": "polygon",
"points": "200,100 200,150 150,200 100,150 100,100",
"fill": "yellow"
},
{
"type": "polygon",
"points": "800,400 800,450 750,500 800,550 800,500",
"fill": "yellow"
},
{
"type": "polygon",
"points": "300,700 300,750 250,800 300,850 300,700",
"fill": "yellow"
},
{
"type": "polygon",
"points": "600,200 600,250 550,300 600,350 600,200",
"fill": "yellow"
},
{
"type": "polygon",
"points": "900,500 900,550 850,600 900,650 900,500",
"fill": "yellow"
}
]

svg_block = _compose_svg(primitives)
print(svg_block)