import terser from '@rollup/plugin-terser';

export default {
  input: 'src/index.js',
  output: [
    {
      file: 'dist/ezauth.iife.js',
      format: 'iife',
      name: 'EZAuth',
      sourcemap: true,
    },
    {
      file: 'dist/ezauth.esm.js',
      format: 'es',
      sourcemap: true,
    },
    {
      file: 'dist/ezauth.cjs',
      format: 'cjs',
      exports: 'named',
      sourcemap: true,
    },
  ],
  plugins: [terser()],
};
