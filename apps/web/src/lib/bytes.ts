/** A size in bytes, as a reader would say it: "812 B", "1.5 KB", "24 MB".
 *
 * One below ten keeps a decimal, because "1 MB" and "1.9 MB" are nearly
 * double; above ten the decimal is noise. Moved here from the dataset
 * application when §507's job files needed the same words for the same
 * number. */
export function bytesText(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
}
