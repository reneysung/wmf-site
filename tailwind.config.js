/**
 * 產生 assets/tailwind.css 的設定。
 *   npx tailwindcss@3.4.19 -i tools/tailwind-in.css -o assets/tailwind.css --minify
 *
 * ⚠️ 版本要釘 3.4.19。這份設定是從 blog 頁面原本的 inline tailwind.config 還原的，
 *    用「只有 index.html + cases」當 content 重建過一次，產出跟當時站上的
 *    assets/tailwind.css **位元組完全相同**，才確定還原正確。換版本會讓既有頁面樣式漂移。
 */
module.exports = {
  content: ['./**/*.html'],
  theme: {
    extend: {
      colors: {
        ink: '#0F1419', navy: '#1B2D4A', navy2: '#243957',
        gold: '#C49A6C', gold2: '#D9B98A',
        ai: '#7C5CFF', ai2: '#9F87FF',
        cream: '#F8F4ED', cream2: '#EFE8DA'
      },
      fontFamily: {
        serif: ['"Noto Serif TC"', 'serif'],
        sans: ['"Noto Sans TC"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace']
      }
    }
  }
}
