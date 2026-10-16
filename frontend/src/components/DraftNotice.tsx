/** Shown on legal pages until a lawyer has reviewed them (roadmap item 8). */
export default function DraftNotice() {
  return (
    <div className="draft-notice" role="note">
      <strong>Draft.</strong> Written from public guidance (Lowe v. SEC publisher&apos;s exclusion, FTC rules on earnings and
      performance claims, SEC Marketing Rule practices) to guide development. It is not legal advice and must be reviewed by a lawyer before
      QuantDesk is offered to the public.
    </div>
  );
}
