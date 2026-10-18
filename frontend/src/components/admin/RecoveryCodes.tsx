import { Download } from 'lucide-react';
import { Button } from '../ui';
import { CopyBlock } from '../account/CopyBlock';

/** Freshly made recovery codes: shown once, with copy and download. */
export const RecoveryCodes = ({ codes }: { codes: string[] }) => {
  const text = codes.join('\n');
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Debatr admin recovery codes (each works once)\n\n${text}\n`], { type: 'text/plain' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'debatr-admin-recovery-codes.txt';
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="grid gap-3">
      <p className="text-sm leading-relaxed text-muted">
        Each code signs you in once if your phone is lost. Keep them somewhere safe, apart from your password: they are
        shown only now.
      </p>
      <CopyBlock text={text} label="Copy the codes" />
      <Button variant="secondary" size="sm" icon={<Download className="size-4" />} onClick={download} className="w-fit">
        Download as a text file
      </Button>
    </div>
  );
};
