/** @type {import('tailwindcss').Config} */
const config = {
  darkMode: ['class'],
  content: [
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
          hover: 'hsl(var(--primary-hover))',
          light: 'hsl(var(--primary-light))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))',
          background: 'hsl(var(--success-bg))',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          background: 'hsl(var(--warning-bg))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        canvas: {
          bg: 'hsl(var(--canvas-bg))',
          border: 'hsl(var(--canvas-border))',
          grid: 'hsl(var(--canvas-grid))',
          guide: 'hsl(var(--canvas-guide))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      spacing: {
        'editor-header': '48px',
        'editor-sidebar': '280px',
        'editor-panel': '320px',
      },
      fontSize: {
        'editor-xs': ['12px', { lineHeight: '16px' }],
        'editor-sm': ['13px', { lineHeight: '20px' }],
        'editor-base': ['14px', { lineHeight: '20px' }],
        'editor-lg': ['16px', { lineHeight: '24px', fontWeight: '500' }],
        'editor-xl': ['20px', { lineHeight: '28px', fontWeight: '600' }],
        'editor-2xl': ['24px', { lineHeight: '32px', fontWeight: '600' }],
      },
    },
  },
  plugins: [],
};

export default config;
