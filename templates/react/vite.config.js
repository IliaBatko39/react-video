import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' — относительные пути в dist/: рендер отдаёт dist/ своим HTTP-сервером из любой папки.
export default defineConfig({
  base: './',
  plugins: [react()],
});
