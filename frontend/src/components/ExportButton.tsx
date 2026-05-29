import { memo, useCallback } from 'react';
import { Button } from '@/components/ui/Button';
import { exportTableToCSV } from '@/utils/csvExport';

interface ExportButtonProps {
  headers: string[];
  rows: unknown[][];
  filename: string;
  label?: string;
}

export const ExportButton = memo(function ExportButton({
  headers,
  rows,
  filename,
  label = '导出 CSV',
}: ExportButtonProps) {
  const handleExport = useCallback(() => {
    exportTableToCSV(headers, rows, filename);
  }, [headers, rows, filename]);

  return (
    <Button variant="ghost" onClick={handleExport} disabled={rows.length === 0}>
      {label}
    </Button>
  );
});
