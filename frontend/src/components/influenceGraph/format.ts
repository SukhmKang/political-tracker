export function formatMoney(amount: number | null): string {
  if (amount == null) return "Unknown";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatMoneyOrDash(amount?: number | null): string {
  return amount == null ? "-" : formatMoney(amount);
}

export function formatCompactMoney(amount?: number | null): string {
  if (amount == null) return "";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    style: "currency",
    currency: "USD",
    maximumFractionDigits: amount >= 1_000_000 ? 1 : 0,
  }).format(amount);
}

export function formatDate(value?: string | null): string {
  if (!value) return "";
  const dateOnlyMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(new Date(Number(year), Number(month) - 1, Number(day)));
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function truncate(value: string, max = 34): string {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

export function titleize(value?: string | null): string | null {
  if (!value) return null;
  return value
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export function relationshipSummary(_sourceName: string, _targetName: string, relationshipType?: string | null): string {
  return relationshipType ?? "Relationship details unavailable.";
}
