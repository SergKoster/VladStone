import { t } from "../../i18n";

export function Profile({
  createdAt,
  email,
  nickname,
}: {
  createdAt?: string;
  email: string;
  nickname: string;
}) {
  const createdDate = createdAt ? new Date(createdAt).toLocaleDateString("ru-RU") : "Сегодня";

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>{t.profile}</h1>
          <p>{email || "Google/dev account"}</p>
        </div>
      </header>
      <section className="metrics">
        <Metric label="Никнейм" value={nickname} />
        <Metric label="Вход" value="Email / Google" />
        <Metric label="Создан" value={createdDate} />
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}
