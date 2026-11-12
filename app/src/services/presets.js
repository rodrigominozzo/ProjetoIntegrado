// Modelos por segmento: terminologia + serviços iniciais. Torna a plataforma genérica.
export const SEGMENTS = {
  fisioterapia: {
    label: 'Fisioterapia',
    terms: { cliente: 'paciente', clientes: 'pacientes', profissional: 'fisioterapeuta', profissionais: 'fisioterapeutas', sessao: 'sessão', sessoes: 'sessões', documento: 'pedido médico' },
    services: [
      { name: 'Avaliação de fisioterapia', duration_min: 60, price: 120, is_entry: 1, package_sessions: 10, package_session_price: 120, sessions_per_week: 2, requires_document: 1, document_label: 'pedido médico', keywords: 'dor,lombar,coluna,joelho,ombro,fisioterapia,travou,torção,lesão,pós-operatório,cirurgia,postura', package_of: 'Sessão de fisioterapia' },
      { name: 'Sessão de fisioterapia', duration_min: 60, price: 120, keywords: 'sessão' },
      { name: 'Pilates clínico', duration_min: 50, price: 90, keywords: 'pilates,alongamento,postura' },
      { name: 'RPG', duration_min: 60, price: 140, keywords: 'rpg,reeducação postural,escoliose' },
    ],
  },
  odontologia: {
    label: 'Odontologia',
    terms: { cliente: 'paciente', clientes: 'pacientes', profissional: 'dentista', profissionais: 'dentistas', sessao: 'consulta', sessoes: 'consultas', documento: 'raio-x ou encaminhamento' },
    services: [
      { name: 'Avaliação odontológica', duration_min: 30, price: 0, is_entry: 1, keywords: 'dente,dor de dente,avaliação,consulta,gengiva,siso' },
      { name: 'Limpeza (profilaxia)', duration_min: 45, price: 180, keywords: 'limpeza,tártaro,profilaxia' },
      { name: 'Clareamento', duration_min: 60, price: 900, keywords: 'clareamento,branqueamento,dente amarelo' },
      { name: 'Manutenção de aparelho', duration_min: 30, price: 150, keywords: 'aparelho,ortodontia,manutenção' },
    ],
  },
  psicologia: {
    label: 'Psicologia',
    terms: { cliente: 'paciente', clientes: 'pacientes', profissional: 'psicólogo(a)', profissionais: 'psicólogos', sessao: 'sessão', sessoes: 'sessões', documento: 'encaminhamento' },
    services: [
      { name: 'Primeira sessão (acolhimento)', duration_min: 50, price: 180, is_entry: 1, package_sessions: 4, package_session_price: 180, sessions_per_week: 1, keywords: 'ansiedade,depressão,terapia,psicólogo,triste,estresse,luto', package_of: 'Sessão de psicoterapia' },
      { name: 'Sessão de psicoterapia', duration_min: 50, price: 180, keywords: 'sessão' },
      { name: 'Terapia de casal', duration_min: 80, price: 280, keywords: 'casal,relacionamento' },
    ],
  },
  estetica: {
    label: 'Estética',
    terms: { cliente: 'cliente', clientes: 'clientes', profissional: 'esteticista', profissionais: 'esteticistas', sessao: 'sessão', sessoes: 'sessões', documento: 'foto da área' },
    services: [
      { name: 'Avaliação estética', duration_min: 30, price: 0, is_entry: 1, package_sessions: 6, package_session_price: 200, sessions_per_week: 1, keywords: 'avaliação,manchas,flacidez,celulite,gordura localizada' },
      { name: 'Limpeza de pele', duration_min: 60, price: 160, keywords: 'limpeza de pele,cravos,acne' },
      { name: 'Depilação a laser', duration_min: 30, price: 120, keywords: 'depilação,laser,pelos' },
    ],
  },
  veterinaria: {
    label: 'Veterinária / Pet',
    terms: { cliente: 'tutor', clientes: 'tutores', profissional: 'veterinário(a)', profissionais: 'veterinários', sessao: 'consulta', sessoes: 'consultas', documento: 'carteira de vacinação' },
    services: [
      { name: 'Consulta veterinária', duration_min: 30, price: 150, is_entry: 1, keywords: 'consulta,doente,vomitando,machucado,cachorro,gato' },
      { name: 'Vacinação', duration_min: 15, price: 90, keywords: 'vacina,vacinação,v10,raiva' },
      { name: 'Banho e tosa', duration_min: 60, price: 80, keywords: 'banho,tosa' },
    ],
  },
  medicina: {
    label: 'Clínica médica',
    terms: { cliente: 'paciente', clientes: 'pacientes', profissional: 'médico(a)', profissionais: 'médicos', sessao: 'consulta', sessoes: 'consultas', documento: 'exames ou encaminhamento' },
    services: [
      { name: 'Consulta clínica', duration_min: 30, price: 250, is_entry: 1, keywords: 'consulta,dor,febre,exame,check-up' },
      { name: 'Retorno', duration_min: 20, price: 0, keywords: 'retorno,resultado de exame' },
    ],
  },
  generico: {
    label: 'Outro / Genérico',
    terms: { cliente: 'cliente', clientes: 'clientes', profissional: 'profissional', profissionais: 'profissionais', sessao: 'atendimento', sessoes: 'atendimentos', documento: 'documento' },
    services: [{ name: 'Atendimento', duration_min: 60, price: 100, is_entry: 1, keywords: 'atendimento,agendar,horário' }],
  },
};

export const DEFAULT_HOURS = { 1: ['07:00', '20:00'], 2: ['07:00', '20:00'], 3: ['07:00', '20:00'], 4: ['07:00', '20:00'], 5: ['07:00', '20:00'], 6: ['08:00', '12:00'] };
export const DEFAULT_SCHEDULE = {
  1: [['07:00', '11:00'], ['12:00', '20:00']], 2: [['07:00', '11:00'], ['12:00', '20:00']], 3: [['07:00', '11:00'], ['12:00', '20:00']],
  4: [['07:00', '11:00'], ['12:00', '20:00']], 5: [['07:00', '11:00'], ['12:00', '20:00']],
};
export const termsFor = (tenant) => ({ ...SEGMENTS.generico.terms, ...(SEGMENTS[tenant.segment]?.terms || {}), ...JSON.parse(tenant.terms_json || '{}') });
