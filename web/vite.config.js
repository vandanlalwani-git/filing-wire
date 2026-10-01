import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base './' : the site lives at /filing-wire/ on GitHub Pages and reads its
// data from ./data/... relative to the page, so every path stays relative.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
})
