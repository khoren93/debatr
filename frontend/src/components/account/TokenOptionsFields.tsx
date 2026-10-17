import { Label, Segmented } from '../ui';
import { FormField } from './FormField';
import { EXPIRY_OPTIONS, type TokenOptions } from './tokenOptions';

/** Name, spending limit and expiry of a new API token. */
export const TokenOptionsFields = ({ value, onChange }: { value: TokenOptions; onChange: (value: TokenOptions) => void }) => (
  <div className="grid gap-4">
    <FormField
      label="Name"
      value={value.name}
      onChange={(e) => onChange({ ...value, name: e.target.value })}
      maxLength={100}
      autoComplete="off"
      hint="Where it is used, e.g. “laptop” or “Claude Desktop”."
    />
    <FormField
      label="Spending limit, $"
      optional
      inputMode="decimal"
      placeholder="No limit"
      value={value.limit}
      onChange={(e) => onChange({ ...value, limit: e.target.value })}
      autoComplete="off"
      hint="Credits the token may spend in total. 0 allows free models only. Recommended for AI agents."
    />
    <div>
      <Label>Expires</Label>
      <Segmented className="mt-1.5" size="sm" options={EXPIRY_OPTIONS} value={value.expiry} onChange={(expiry) => onChange({ ...value, expiry })} />
    </div>
  </div>
);
