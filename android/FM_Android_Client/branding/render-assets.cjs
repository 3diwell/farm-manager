// Build static launcher PNGs from the approved vector; no image generation service or network.
// node render-assets.cjs [path/to/msedge-or-chrome]
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const icon=fs.readFileSync(path.join(__dirname,'fm-glass.svg'),'utf8').replace(/<\?xml[^>]*>/,'');
const logo=fs.readFileSync(path.join(__dirname,'3diwell-original.svg'),'utf8').replace(/<\?xml[^>]*>/,'');
let browser;
(async()=>{
    browser=await chromium.launch({headless:true,...(process.argv[2]?{executablePath:process.argv[2]}:{})});
    const page=await browser.newPage({deviceScaleFactor:1});
    await page.route('**/*',route=>route.abort());
    async function raster(svg,width,height,destination,background='transparent') {
        await page.setViewportSize({width,height});
        await page.setContent('<style>html,body{margin:0;background:'+background+'}svg{display:block;width:'+width+'px;height:'+height+'px}</style>'+svg);
        fs.mkdirSync(path.dirname(destination),{recursive:true});
        await page.screenshot({path:destination,omitBackground:background==='transparent'});
    }
    for(const [density,size] of Object.entries({mdpi:48,hdpi:72,xhdpi:96,xxhdpi:144,xxxhdpi:192})) {
        await raster(icon,size,size,path.join(root,'app/src/main/res','mipmap-'+density,'ic_launcher.png'));
    }
    await raster(icon,1024,1024,path.join(__dirname,'fm-glass-1024.png'));
    await raster(logo,362,81,path.join(__dirname,'3diwell-on-dark-check.png'),'#18181B');
    console.log('Rendered approved glass icon at all five Android densities; original white/orange wordmark preview.');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();});
