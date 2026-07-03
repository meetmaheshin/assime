// Render AARTH icon assets (orange 'A' monogram) from SVG -> PNG using sharp,
// then @capacitor/assets turns these into all Android densities + adaptive icons.
import sharp from "sharp";
import { mkdirSync } from "fs";

mkdirSync("assets", { recursive: true });

// Bold geometric 'A' drawn as strokes (no font dependency).
const A = (color, w = 96) => `
  <g fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">
    <path d="M330 762 L512 262 L694 762"/>
    <path d="M398 596 L626 596"/>
  </g>`;

const gradient = `
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#ff9d2f"/>
    <stop offset="1" stop-color="#ff5722"/>
  </linearGradient></defs>`;

const bg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">
  ${gradient}<rect width="1024" height="1024" fill="url(#g)"/></svg>`;

// Foreground for adaptive icon: white 'A' on transparent, inside the safe zone.
const fg = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">
  ${A("#ffffff", 100)}</svg>`;

// Full legacy icon: rounded orange square + white 'A'.
const icon = `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024">
  ${gradient}<rect width="1024" height="1024" rx="220" fill="url(#g)"/>
  ${A("#ffffff", 100)}</svg>`;

// Splash: 'A' mark on the app's dark background.
const splash = `<svg xmlns="http://www.w3.org/2000/svg" width="2732" height="2732">
  ${gradient}<rect width="2732" height="2732" fill="#0e1116"/>
  <g transform="translate(854,854) scale(1.0)">${A("url(#g)", 110)}</g></svg>`;

const jobs = [
  ["assets/icon.png", icon],
  ["assets/icon-foreground.png", fg],
  ["assets/icon-background.png", bg],
  ["assets/splash.png", splash],
  ["assets/splash-dark.png", splash],
];
for (const [file, svg] of jobs) {
  await sharp(Buffer.from(svg)).png().toFile(file);
  console.log("wrote", file);
}
