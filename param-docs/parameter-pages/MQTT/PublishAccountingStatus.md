# Parameter `PublishAccountingStatus`
Default Value: `false`

Publish the custom analog reader accounting snapshot on
`<main topic>/accounting/status`. This separate diagnostic message preserves
uncertainty bounds, unknown estimates and restart information. It does not change
existing readings, units or Home Assistant discovery.

Messages are not retained, regardless of RetainMessages. Consumers must check
capture timestamps and boot identities; messages are not proof of current physical
accuracy or broker delivery. A failed earlier processing stage can prevent an
update. This option is useful with the frozen PolarV1 reader only.
