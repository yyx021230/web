import Link from 'next/link';
import { ArrowUpRight, CalendarClock, Layers3, UsersRound } from 'lucide-react';
import styles from './workflow-gallery.module.css';

const workflows = [
  { id: 'batch', href: '/workflows/hermes', label: '批量生产', title: '多账号图文生产', description: '选好账号、篇数与车型，一起创作。', icon: UsersRound },
  { id: 'single', href: '/workflows/hermes/single', label: '精准单篇', title: '指定图文类型创作', description: '选定文案方向与画面风格，创作一篇。', icon: Layers3 },
  { id: 'publish', href: '/workflows/hermes/publish', label: '发布计划', title: '审核内容发布排期', description: '安排账号与时间，发布接口待接入。', icon: CalendarClock },
] as const;

function GalleryVisual({ kind }: { kind: typeof workflows[number]['id'] }) {
  return (
    <div className={styles.art} data-visual={kind} aria-hidden="true">
      {kind === 'batch' && <img className={styles.stack} src="/workflows/hermes-cover-stack.png" alt="" width={1086} height={1448} />}
      {kind === 'single' && <img className={styles.single} src="/workflows/single-post-cover.png" alt="" width={1086} height={1448} />}
      {kind === 'publish' && <div className={styles.schedule}>
        <span className={styles.scheduleLabel}>排期示意</span>
        {['09:30', '13:20', '18:40'].map((time, index) => (
          <div key={time} className={styles.scheduleItem}>
            <img src="/workflows/single-post-cover.png" alt="" width={1086} height={1448} />
            <div><strong>{time}</strong><span>内容 {String(index + 1).padStart(2, '0')}</span></div>
            <span className={styles.scheduleState}><i />待发布</span>
          </div>
        ))}
      </div>}
    </div>
  );
}

export default function WorkflowGalleryCards() {
  return <div className={styles.container}>
    <div className={styles.grid} aria-label="工作流入口">
      {workflows.map(({ id, href, label, title, description, icon: Icon }) => (
        <Link key={id} href={href} className={styles.card} data-workflow={id} aria-labelledby={`workflow-${id}-title`} aria-describedby={`workflow-${id}-description`}>
          <GalleryVisual kind={id} />
          <div className={styles.copy}>
            <span className={styles.eyebrow}><Icon size={13} strokeWidth={1.7} />{label}</span>
            <h2 id={`workflow-${id}-title`}>{title}</h2>
            <p id={`workflow-${id}-description`}>{description}</p>
          </div>
          <span className={styles.arrow} aria-hidden="true"><ArrowUpRight size={16} strokeWidth={1.6} /></span>
        </Link>
      ))}
    </div>
  </div>;
}
