# Portal login is a split page with a dithered swirl brand panel

Status: accepted.

Supersedes ADR 0002 and amends ADR 0045. The Portal login shell is a split page with no top navigation. The left brand panel holds the Login Network, the Brand Logo on its light badge plate, and the words "Vans Coding Router". The right login pane holds 歡迎回來, the tagline, the sign-in button and a one-line hint. The product name appears once, in the brand panel. The Theme toggle floats top-right. On narrow screens the brand panel stacks on top at 40% of the viewport height.

The Login Network is now a swirl shaded with a 4x4 Bayer dither, drawn with plain WebGL. It has no Three.js and no CDN load. Its palette is fixed at `#220011` / `#00ffff` on both Themes. Only the small dither accent above 歡迎回來 and the sign-in button's focus ring follow the Theme; they reuse the two swirl colours. With reduced motion it draws one still frame. Without WebGL the panel keeps its `#220011` background (silent degrade, as before).

Chosen from prototype variants on the `prototype/login-swirl` branch: variant B4 (`/portal?variant=B4`). It was iterated to its final form there, with the logo moved above the brand words.

## Considered Options

- **Scaffold React, shadcn and Tailwind to drop in the `DitheringShader` component.** Rejected for the same reason as ADR 0002: the Portal is vanilla HTML/CSS/JS, and one effect does not justify a frontend build.
- **Full-bleed swirl behind a floating login card (variant A).** Rejected. The card fights the pattern and the name still repeats.
- **Swirl confined to a banner on the login card (variant C).** Rejected. Too small to carry the page.
- **A 凡思超能力 wordmark image in the brand panel (variant B2).** Rejected by the owner in favour of the English name.
- **A footer with 使用說明 / 隱私權 / 聯絡我們 links.** Left out. There are no pages to link to yet.

## Consequences

- The Brand Logo no longer appears in navigation chrome on the login shell. It sits in the brand panel.
- The product name in the brand panel (`.login-brand-title`, up to 84px) is display type. It is the one font size exempt from ADR 0045's type scale. Everything in the login pane stays on the scale (32px 歡迎回來, 14px tagline, 12px hint).
- The hint 第一次登入會自動建立帳號 shows only while registration is open. `/auth/config` now reports `open_registration` (runtime setting included), because Google login creates a new user only then (`PortalUseCase.google_login`).
