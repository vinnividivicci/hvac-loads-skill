# /// script
# dependencies = ["matplotlib>=3.8"]
# ///
"""Synthetic vector plan set (French, metric) for testing the skill. Usage: python make_plans.py out.pdf

Deliberate traps: printed scale 1:50 but drawn at 1:75; the east dimension chain on the ground floor
reads 4 800 + 3 150 against an 8 000 overall (drawing inconsistency).
"""
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["font.family"] = "DejaVu Sans"
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import sys
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("maison_laval_plans.pdf")
OUT.parent.mkdir(parents=True, exist_ok=True)
S = 1000 / 75  # paper mm per metre (drawn at 1:75)
W, H = 279.4, 215.9
OX, OY = 45, 45  # plan origin on paper (mm)


def P(x, y):
    return OX + x * S, OY + y * S


def page(title):
    fig = plt.figure(figsize=(W / 25.4, H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.plot([8, W - 8, W - 8, 8, 8], [8, 8, H - 8, H - 8, 8], color="k", lw=0.8)
    ax.text(12, H - 16, title, fontsize=13, weight="bold")
    ax.text(W - 12, 12, "RÉSIDENCE UNIFAMILIALE — 123, rue Exemple, Laval (Québec)", ha="right", fontsize=7)
    return fig, ax


def walls(ax, outline, parts):
    xs, ys = zip(*[P(x, y) for x, y in outline + [outline[0]]])
    ax.plot(xs, ys, color="k", lw=3.2, solid_joinstyle="miter")
    for (x1, y1), (x2, y2) in parts:
        a, b = P(x1, y1), P(x2, y2)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="k", lw=1.4)


def opening(ax, x, y, width, orient, tag, door=False):
    """Draw an opening centred at plan (x, y) on a wall running along x ('h') or y ('v')."""
    c = P(x, y)
    half = width * S / 2
    if orient == "h":
        ax.plot([c[0] - half, c[0] + half], [c[1], c[1]], color="white", lw=4.2, solid_capstyle="butt")
        for dy in (-0.9, 0.9):
            ax.plot([c[0] - half, c[0] + half], [c[1] + dy, c[1] + dy], color="k", lw=0.5)
        ax.text(c[0], c[1] + (3.2 if y > 4 else -5), tag, ha="center", fontsize=6)
    else:
        ax.plot([c[0], c[0]], [c[1] - half, c[1] + half], color="white", lw=4.2, solid_capstyle="butt")
        for dx in (-0.9, 0.9):
            ax.plot([c[0] + dx, c[0] + dx], [c[1] - half, c[1] + half], color="k", lw=0.5)
        ax.text(c[0] + (3 if x > 5 else -3), c[1], tag, ha="left" if x > 5 else "right", va="center", fontsize=6)
    if door:
        ax.add_patch(matplotlib.patches.Arc(c if orient == "h" else c, 2 * half, 2 * half, theta1=0, theta2=90, lw=0.4))


def dim(ax, a, b, text, off, orient):
    """Dimension line between plan points a and b, offset (paper mm) outward."""
    pa, pb = P(*a), P(*b)
    if orient == "h":
        y = pa[1] + off
        ax.plot([pa[0], pb[0]], [y, y], color="k", lw=0.4)
        for px in (pa[0], pb[0]):
            ax.plot([px, px], [pa[1] + (2 if off > 0 else -2), y + (1.5 if off > 0 else -1.5)], color="k", lw=0.3)
            ax.plot([px - 1, px + 1], [y - 1, y + 1], color="k", lw=0.6)
        ax.text((pa[0] + pb[0]) / 2, y + 1, text, ha="center", va="bottom", fontsize=6)
    else:
        x = pa[0] + off
        ax.plot([x, x], [pa[1], pb[1]], color="k", lw=0.4)
        for py in (pa[1], pb[1]):
            ax.plot([pa[0] + (2 if off > 0 else -2), x + (1.5 if off > 0 else -1.5)], [py, py], color="k", lw=0.3)
            ax.plot([x - 1, x + 1], [py - 1, py + 1], color="k", lw=0.6)
        ax.text(x - 1, (pa[1] + pb[1]) / 2, text, ha="right", va="center", fontsize=6, rotation=90)


def label(ax, x, y, name, area):
    c = P(x, y)
    ax.text(c[0], c[1] + 1.5, name, ha="center", fontsize=6.5, weight="bold")
    ax.text(c[0], c[1] - 2.5, area, ha="center", fontsize=5.5)


def north(ax, deg=15):
    cx, cy, r = W - 30, H - 35, 10
    ax.add_patch(matplotlib.patches.Circle((cx, cy), r, fill=False, lw=0.6))
    a = math.radians(deg)
    tip = (cx + r * math.sin(a), cy + r * math.cos(a))
    base = (cx - 0.6 * r * math.sin(a), cy - 0.6 * r * math.cos(a))
    ax.annotate("", xy=tip, xytext=base, arrowprops=dict(arrowstyle="-|>", lw=1.2, color="k"))
    ax.text(tip[0] + 1.5, tip[1] + 1.5, "N", fontsize=9, weight="bold")


def scale_note(ax, title):
    ax.text(OX + 69, 22, title, ha="center", fontsize=10, weight="bold")
    ax.text(OX + 69, 17, "ÉCHELLE : 1:50", ha="center", fontsize=7)


OUTLINE = [(0, 0), (10.4, 0), (10.4, 8.0), (0, 8.0)]
with PdfPages(OUT) as pdf:
    # ---------- page 1: ground floor ----------
    fig, ax = page("PLAN DU REZ-DE-CHAUSSÉE")
    walls(ax, OUTLINE, [((5.6, 0), (5.6, 8.0)), ((0, 4.8), (10.4, 4.8)), ((3.2, 4.8), (3.2, 8.0))])
    label(ax, 2.8, 2.4, "SALON", "26,9 m²")
    label(ax, 8.0, 2.4, "CUISINE / SALLE À MANGER", "23,0 m²")
    label(ax, 1.6, 6.4, "HALL / ESCALIER", "10,2 m²")
    label(ax, 4.4, 6.4, "S.D'EAU / LAV.", "7,7 m²")
    label(ax, 8.0, 6.4, "SALLE FAMILIALE", "15,4 m²")
    opening(ax, 2.8, 0, 1.2, "h", "F1")
    opening(ax, 0, 2.4, 0.9, "v", "F2")
    opening(ax, 8.0, 0, 1.2, "h", "F1")
    opening(ax, 10.4, 2.4, 1.8, "v", "PF1")
    opening(ax, 1.6, 8.0, 0.915, "h", "P1", door=True)
    opening(ax, 4.4, 8.0, 0.6, "h", "F3")
    opening(ax, 8.0, 8.0, 1.2, "h", "F1")
    opening(ax, 10.4, 6.4, 0.9, "v", "F2")
    dim(ax, (0, 0), (10.4, 0), "10 400", -16, "h")
    dim(ax, (0, 0), (5.6, 0), "5 600", -9, "h")
    dim(ax, (5.6, 0), (10.4, 0), "4 800", -9, "h")
    dim(ax, (0, 0), (0, 8.0), "8 000", -16, "v")
    dim(ax, (0, 0), (0, 4.8), "4 800", -9, "v")
    dim(ax, (0, 4.8), (0, 8.0), "3 200", -9, "v")
    dim(ax, (10.4, 0), (10.4, 4.8), "4 800", 12, "v")
    dim(ax, (10.4, 4.8), (10.4, 8.0), "3 150", 12, "v")
    dim(ax, (0, 8.0), (3.2, 8.0), "3 200", 9, "h")
    dim(ax, (3.2, 8.0), (5.6, 8.0), "2 400", 9, "h")
    north(ax)
    scale_note(ax, "REZ-DE-CHAUSSÉE")
    pdf.savefig(fig)
    plt.close(fig)

    # ---------- page 2: upper floor ----------
    fig, ax = page("PLAN DE L'ÉTAGE")
    walls(ax, OUTLINE, [((0, 4.0), (10.4, 4.0)), ((3.2, 0), (3.2, 4.0)), ((7.0, 0), (7.0, 4.0)),
                        ((5.2, 4.0), (5.2, 8.0)), ((7.2, 4.0), (7.2, 8.0))])
    label(ax, 1.6, 2.0, "HALL / ESCALIER", "12,8 m²")
    label(ax, 5.1, 2.0, "CHAMBRE 2", "15,2 m²")
    label(ax, 8.7, 2.0, "CHAMBRE 3", "13,6 m²")
    label(ax, 2.6, 6.0, "CHAMBRE PRINCIPALE", "20,8 m²")
    label(ax, 6.2, 6.0, "S.D.B.", "8,0 m²")
    label(ax, 8.8, 6.0, "WALK-IN", "12,8 m²")
    opening(ax, 0, 2.0, 0.9, "v", "F2")
    opening(ax, 5.1, 0, 1.2, "h", "F1")
    opening(ax, 8.7, 0, 1.2, "h", "F1")
    opening(ax, 10.4, 2.0, 0.9, "v", "F2")
    opening(ax, 2.6, 8.0, 1.2, "h", "F1")
    opening(ax, 0, 6.0, 0.9, "v", "F2")
    opening(ax, 6.2, 8.0, 0.6, "h", "F3")
    dim(ax, (0, 0), (10.4, 0), "10 400", -16, "h")
    dim(ax, (0, 0), (3.2, 0), "3 200", -9, "h")
    dim(ax, (3.2, 0), (7.0, 0), "3 800", -9, "h")
    dim(ax, (7.0, 0), (10.4, 0), "3 400", -9, "h")
    dim(ax, (0, 0), (0, 8.0), "8 000", -16, "v")
    dim(ax, (0, 0), (0, 4.0), "4 000", -9, "v")
    dim(ax, (0, 4.0), (0, 8.0), "4 000", -9, "v")
    dim(ax, (0, 8.0), (5.2, 8.0), "5 200", 9, "h")
    dim(ax, (5.2, 8.0), (7.2, 8.0), "2 000", 9, "h")
    dim(ax, (7.2, 8.0), (10.4, 8.0), "3 200", 9, "h")
    north(ax)
    scale_note(ax, "ÉTAGE")
    pdf.savefig(fig)
    plt.close(fig)

    # ---------- page 3: basement + notes + schedule ----------
    fig, ax = page("PLAN DU SOUS-SOL, NOTES ET TABLEAU DES OUVERTURES")
    walls(ax, OUTLINE, [((0, 5.0), (10.4, 5.0))])
    label(ax, 5.2, 2.5, "SALLE DE JEUX (FINIE, CHAUFFÉE)", "52,0 m²")
    label(ax, 5.2, 6.5, "MÉCANIQUE / RANGEMENT (CHAUFFÉ)", "31,2 m²")
    opening(ax, 2.6, 0, 0.8, "h", "F4")
    opening(ax, 7.8, 0, 0.8, "h", "F4")
    dim(ax, (0, 0), (10.4, 0), "10 400", -16, "h")
    dim(ax, (0, 0), (0, 8.0), "8 000", -16, "v")
    dim(ax, (0, 0), (0, 5.0), "5 000", -9, "v")
    dim(ax, (0, 5.0), (0, 8.0), "3 000", -9, "v")
    north(ax)
    scale_note(ax, "SOUS-SOL")
    x0 = 195
    notes = [
        "TABLEAU DES OUVERTURES (L x H, mm)",
        "F1  fenêtre à battant   1 200 x 1 500   allège 900",
        "F2  fenêtre à battant     900 x 1 200   allège 900",
        "F3  fenêtre à auvent      600 x   900   allège 1 200",
        "F4  fenêtre de sous-sol   800 x   400   allège 1 600",
        "PF1 porte-fenêtre      1 800 x 2 030",
        "P1  porte d'entrée isolée 915 x 2 030",
        "Fenêtres PVC triple vitrage, U = 1,20 W/m²K, CGCS 0,30.",
        "",
        "NOTES",
        "Hauteur sous plafond : sous-sol 2 300, RDC 2 440,",
        "  étage 2 440. Planchers (solives) : 300.",
        "Plancher du RDC à 600 au-dessus du sol fini ;",
        "  dalle du sous-sol à 2 000 sous le sol fini.",
        "Murs ext. : 2x6 à 406 c/c, laine R-24, isolant rigide",
        "  continu R-5 ext., gypse 12,7.",
        "Toit : fermes, entretoit ventilé, R-50 soufflé,",
        "  pente 6/12, toit à quatre versants.",
        "Fondation : béton 200, isolant int. RSI 3,52 pleine",
        "  hauteur ; dalle : isolant RSI 1,76 sous toute la surface.",
        "Chauffage : thermopompe centrale, conduits dans",
        "  l'enveloppe chauffée. VRC 60 L/s, efficacité 70 %.",
        "",
        "SUPERFICIES",
        "RDC 83,2 m² ; étage 83,2 m² ; sous-sol 83,2 m²",
        "Superficie habitable (hors sous-sol) : 166,4 m²",
        "Surface vitrée totale : 21,6 m²",
    ]
    for i, t in enumerate(notes):
        ax.text(x0, H - 30 - i * 5.2, t, fontsize=5.6, weight="bold" if t.isupper() and t else "normal",
                family="DejaVu Sans Mono" if t.startswith(("F", "P")) and "  " in t else "DejaVu Sans")
    pdf.savefig(fig)
    plt.close(fig)
print(OUT)
