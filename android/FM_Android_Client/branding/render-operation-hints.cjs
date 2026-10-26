// Reproduce the approved SVGs as transparent, high-density Android resources.
// Usage: node branding/render-operation-hints.cjs [absolute/path/to/sharp]
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const sharp = require(process.argv[2] || 'sharp');
const root = path.resolve(__dirname, '..');
const assets = {
  'printer-portal.svg': 'hint_printer.png',
  'warehouse-spool-rack.svg': 'hint_warehouse.png',
  'spool-full-black.svg': 'hint_spool_full.png',
  'spool-low-black.svg': 'hint_spool_low.png',
  'brand-check.svg': 'hint_brand_check.png',
};
const destination = path.join(root, 'app/src/main/res/drawable-nodpi');
async function main() {
  fs.mkdirSync(destination, {recursive: true});
  const manifest = {source: 'Android_Operation_Hints_v06_Approved', assets: []};
  for (const [source, output] of Object.entries(assets)) {
    const svg = fs.readFileSync(path.join(__dirname, 'operation-hints', source));
    const png = await sharp(svg, {density: 192})
      .resize({width: 384, height: 384, fit: 'inside'})
      .png().toBuffer();
    fs.writeFileSync(path.join(destination, output), png);
    const meta = await sharp(png).metadata();
    manifest.assets.push({source, output, width: meta.width, height: meta.height,
      svgSha256: crypto.createHash('sha256').update(svg).digest('hex'),
      pngSha256: crypto.createHash('sha256').update(png).digest('hex')});
  }
  fs.writeFileSync(path.join(__dirname, 'operation-hints', 'raster-manifest.json'), JSON.stringify(manifest, null, 2)+'\n');
  console.log('Rendered 5 approved icons with transparency; raster manifest saved.');
}
main().catch(error => {console.error(error); process.exitCode=1;});
