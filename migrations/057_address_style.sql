-- Add address_style column for Czech tykání/vykání (informal/formal address)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS address_style VARCHAR(10) DEFAULT 'vykat';
