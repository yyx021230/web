'use client';
import type { ReactNode } from 'react';
import s from './hermes.module.css';

// Schematic thumbnails explain every direction, including types with no local
// library preview. They are deliberately not represented as source examples.
export const PREVIEW_TYPES = [
  'policy_news', 'price_plan', 'car_compare', 'buying_guide', 'drive_review', 'product_features', 'car_lifestyle',
  'headline_poster', 'price_highlight', 'quote_table', 'quote_cards', 'feature_infographic', 'photo_collage', 'scene_poster', 'note_poster', 'studio_poster',
] as const;

function lines(x: number, y: number, width = 50, count = 3) {
  return Array.from({ length: count }, (_, i) => <rect key={i} x={x} y={y + i * 7} width={width - (i === count - 1 ? 12 : 0)} height="2.5" rx="1.25" fill="currentColor" opacity=".28" />);
}
function vehicle(x: number, y: number, scale = 1) {
  return <g transform={`translate(${x} ${y}) scale(${scale})`} fill="currentColor"><path d="M3 17 11 14 20 4 Q22 2 28 2h22q5 0 9 4l10 9 11 4q3 1 3 5v6H0v-8q0-3 3-5Z" opacity=".55" /><path d="m22 7-6 8h42l-7-8Z" fill="white" opacity=".8" /><circle cx="17" cy="29" r="7" /><circle cx="65" cy="29" r="7" /><circle cx="17" cy="29" r="3" fill="white" /><circle cx="65" cy="29" r="3" fill="white" /></g>;
}
function sheet(children: ReactNode) { return <><rect x="12" y="7" width="96" height="130" rx="5" fill="white" />{children}</>; }

export default function HermesTypePreview({ id, small = false }: { id: string; small?: boolean }) {
  const layouts: Record<string, ReactNode> = {
    policy_news: sheet(<><rect x="22" y="18" width="31" height="8" rx="2" fill="currentColor" opacity=".2" /><rect x="22" y="33" width="68" height="8" rx="2" fill="currentColor" />{[54, 75, 96].map(y => <g key={y}><circle cx="25" cy={y + 2} r="3" fill="currentColor" />{lines(34, y, 60, 2)}</g>)}{lines(22, 121, 43, 1)}</>),
    price_plan: sheet(<><rect x="22" y="20" width="57" height="5" rx="2" fill="currentColor" opacity=".5" /><rect x="22" y="36" width="75" height="33" rx="4" fill="currentColor" opacity=".13" /><text x="31" y="61" fontSize="25" fontWeight="600" fill="currentColor">¥ —</text>{lines(22, 79, 73, 3)}<rect x="22" y="109" width="73" height="15" rx="3" fill="currentColor" opacity=".12" /></>),
    car_compare: sheet(<>{lines(22, 20, 73, 1)}{[22, 63].map((x, i) => <g key={x}><rect x={x} y="36" width="35" height="65" rx="3" fill="currentColor" opacity={i ? '.18' : '.08'} /><text x={x + 11} y="56" fontSize="12" fill="currentColor">{i ? 'B' : 'A'}</text>{lines(x + 6, 66, 25, 4)}</g>)}{lines(22, 113, 73, 2)}</>),
    buying_guide: sheet(<>{lines(22, 20, 70, 1)}{[38, 66, 94].map((y, i) => <g key={y}><rect x="21" y={y} width="15" height="15" rx="4" fill="currentColor" opacity=".15" /><text x="26" y={y + 11} fontSize="10" fill="currentColor">{i + 1}</text>{lines(43, y + 2, 51, 3)}</g>)}</>),
    drive_review: sheet(<>{lines(22, 20, 69, 1)}<path d="M23 48h72" stroke="currentColor" strokeWidth="14" strokeDasharray="12 6" opacity=".4" />{[66, 97].map((y, i) => <g key={y}><text x="22" y={y + 8} fontSize="13" fill="currentColor">{i ? '−' : '+'}</text>{lines(39, y, 55, 3)}</g>)}</>),
    product_features: sheet(<>{lines(22, 20, 69, 1)}{[38, 67, 96].map(y => <g key={y}><rect x="22" y={y} width="22" height="20" rx="4" fill="currentColor" opacity=".2" />{lines(53, y + 3, 42, 3)}</g>)}</>),
    car_lifestyle: sheet(<><rect x="21" y="17" width="78" height="44" rx="3" fill="currentColor" opacity=".13" /><circle cx="81" cy="29" r="5" fill="currentColor" opacity=".4" /><path d="m21 56 19-20 17 12 15-11 27 19" fill="currentColor" opacity=".22" />{lines(22, 73, 75, 3)}{lines(22, 104, 75, 3)}</>),
    headline_poster: sheet(<><rect x="23" y="20" width="74" height="13" rx="2" fill="currentColor" /><rect x="23" y="39" width="52" height="13" rx="2" fill="currentColor" opacity=".6" />{vehicle(23, 72, .9)}{lines(24, 118, 69, 1)}</>),
    quote_table: sheet(<>{lines(22, 19, 74, 1)}{[35, 56, 77, 98].map((y, i) => <g key={y}><rect x="21" y={y} width="78" height="18" rx="2" fill="currentColor" opacity={i ? '.08' : '.25'} />{lines(26, y + 7, 39, 1)}<path d={`M71 ${y + 2}v14`} stroke="currentColor" opacity=".15" />{lines(77, y + 7, 24, 1)}</g>)}{lines(23, 125, 62, 1)}</>),
    quote_cards: sheet(<>{lines(22, 18, 70, 1)}{vehicle(35, 30, .6)}{[66, 101].map(y => [22, 63].map(x => <g key={`${x}-${y}`}><rect x={x} y={y} width="35" height="29" rx="4" fill="currentColor" opacity=".12" />{lines(x + 5, y + 6, 25, 1)}<text x={x + 5} y={y + 24} fontSize="13" fontWeight="700" fill="currentColor">¥ —</text></g>))}</>),
    price_highlight: sheet(<>{lines(22, 20, 60, 1)}<text x="22" y="61" fontSize="35" fontWeight="800" fill="currentColor">¥ —</text>{lines(22, 72, 65, 1)}{vehicle(25, 86, .87)}{lines(22, 126, 70, 1)}</>),
    feature_infographic: sheet(<>{lines(22, 21, 74, 1)}{vehicle(26, 61, .82)}<path d="M36 70V42H23M82 75V49h14M52 93v20H23" fill="none" stroke="currentColor" strokeWidth="1" /><circle cx="36" cy="70" r="2" fill="currentColor" />{lines(21, 35, 31, 1)}{lines(73, 41, 34, 1)}{lines(22, 121, 45, 1)}</>),
    photo_collage: sheet(<>{lines(22, 18, 74, 1)}<rect x="21" y="32" width="78" height="44" rx="3" fill="currentColor" opacity=".15" />{vehicle(31, 43, .7)}{[21, 63].map(x => <g key={x}><rect x={x} y="81" width="36" height="30" rx="2" fill="currentColor" opacity=".25" />{lines(x + 4, 94, 28, 1)}</g>)}{lines(22, 122, 63, 1)}</>),
    scene_poster: sheet(<><rect x="12" y="7" width="96" height="130" rx="5" fill="currentColor" opacity=".12" /><circle cx="86" cy="27" r="10" fill="white" /><path d="m12 84 26-39 19 26 16-14 35 31v49H12Z" fill="currentColor" opacity=".17" /><path d="m12 136 90-39" stroke="white" strokeWidth="12" opacity=".6" />{vehicle(26, 86, .88)}{lines(22, 22, 51, 2)}</>),
    note_poster: <><path d="M12 8h96v124l-5 5-6-4-5 4-7-4-6 4-6-4-6 4-6-4-6 4-6-4-6 4-6-4-6 4-6-4-7 4Z" fill="white" />{[32, 48, 64, 80, 96, 112].map(y => <path key={y} d={`M17 ${y}h86`} stroke="currentColor" opacity=".1" />)}<g transform="rotate(-7 60 62)"><rect x="26" y="43" width="69" height="53" fill="currentColor" opacity=".18" />{vehicle(31, 52, .7)}<rect x="45" y="37" width="32" height="11" fill="currentColor" opacity=".3" /></g>{lines(23, 19, 66, 1)}{lines(24, 113, 70, 1)}</>,
    studio_poster: sheet(<>{lines(22, 22, 49, 1)}<ellipse cx="60" cy="101" rx="39" ry="8" fill="currentColor" opacity=".1" />{vehicle(24, 72, .9)}{lines(33, 121, 58, 1)}</>),
  };
  return <span className={s.typePreview} data-small={small} data-type-preview={id} aria-hidden="true"><svg viewBox="0 0 120 144" focusable="false">{layouts[id] || sheet(lines(22, 25, 72, 10))}</svg></span>;
}
