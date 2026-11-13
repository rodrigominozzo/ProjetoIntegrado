// Modelos por segmento: terminologia + catálogo inicial (tudo editável depois no painel).
// O padrão é "clínica multiespecialidade"; os demais servem para negócios de uma especialidade só.
const T = (cliente, clientes, profissional, profissionais, sessao, sessoes, documento) => ({ cliente, clientes, profissional, profissionais, sessao, sessoes, documento });

export const SEGMENTS = {
  clinica: {
    label: 'Clínica multiespecialidade',
    terms: T('paciente', 'pacientes', 'profissional', 'profissionais', 'consulta', 'consultas', 'pedido médico ou encaminhamento'),
    services: [
      { category: 'Consultas', name: 'Consulta clínica geral', duration_min: 30, price: 250, cost: 10, return_days: 30, keywords: 'clinico geral,clínico,consulta,febre,gripe,dor de garganta,check-up,exames de rotina,pressão' },
      { category: 'Consultas', name: 'Consulta dermatológica', duration_min: 40, price: 350, cost: 10, return_days: 30, keywords: 'dermatologista,dermatologia,pele,mancha,acne,espinha,queda de cabelo,unha,coceira,alergia na pele' },
      { category: 'Consultas', name: 'Consulta pediátrica', duration_min: 30, price: 300, cost: 10, return_days: 15, max_age: 17, keywords: 'pediatra,pediatria,criança,bebê,filho,filha' },
      { category: 'Consultas', name: 'Consulta ginecológica', duration_min: 40, price: 320, cost: 15, return_days: 30, keywords: 'ginecologista,ginecologia,preventivo,papanicolau,anticoncepcional,menstruação' },
      { category: 'Consultas', name: 'Consulta nutricional', duration_min: 50, price: 220, cost: 5, return_days: 30, keywords: 'nutricionista,nutrição,dieta,emagrecer,emagrecimento,alimentação' },
      { category: 'Terapias', name: 'Sessão de psicoterapia', duration_min: 50, price: 200, cost: 0, modality: 'ambos', keywords: 'psicólogo,psicologa,psicologia,terapia,ansiedade,depressão,estresse,luto' },
      { category: 'Terapias', name: 'Avaliação de fisioterapia', duration_min: 60, price: 150, cost: 10, is_entry: 1, package_sessions: 10, package_session_price: 120, sessions_per_week: 2, requires_document: 1, document_label: 'pedido médico', package_of: 'Sessão de fisioterapia', keywords: 'fisioterapia,fisioterapeuta,lombar,coluna,joelho,ombro,travou,torção,lesão,pós-operatório', preparation: 'Venha com roupa confortável e traga exames de imagem, se tiver.' },
      { category: 'Terapias', name: 'Sessão de fisioterapia', duration_min: 50, price: 120, cost: 8, keywords: 'sessão de fisioterapia' },
      { category: 'Procedimentos', name: 'Remoção de sinal / lesão de pele', duration_min: 30, buffer_min: 10, price: 450, cost: 90, online_booking: 0, keywords: 'retirar sinal,remover sinal,verruga,pinta', preparation: 'Procedimento agendado somente após avaliação dermatológica.' },
      { category: 'Procedimentos', name: 'Peeling químico', duration_min: 45, buffer_min: 15, price: 380, cost: 95, keywords: 'peeling,manchas,melasma', preparation: 'Evite sol e ácidos na pele 5 dias antes.' },
      { category: 'Exames', name: 'Eletrocardiograma', duration_min: 20, price: 120, cost: 18, keywords: 'eletrocardiograma,ecg,coração', preparation: 'Evite cremes no peito no dia do exame.' },
      { category: 'Exames', name: 'Bioimpedância', duration_min: 20, price: 90, cost: 5, keywords: 'bioimpedância,composição corporal', preparation: 'Jejum de 4 horas e não praticar exercícios no dia.' },
    ],
  },
  odontologia: {
    label: 'Odontologia',
    terms: T('paciente', 'pacientes', 'dentista', 'dentistas', 'consulta', 'consultas', 'raio-x ou encaminhamento'),
    services: [
      { category: 'Consultas', name: 'Avaliação odontológica', duration_min: 30, price: 0, is_entry: 1, keywords: 'dente,dor de dente,avaliação,consulta,gengiva,siso' },
      { category: 'Procedimentos', name: 'Limpeza (profilaxia)', duration_min: 45, buffer_min: 10, price: 180, cost: 25, keywords: 'limpeza,tártaro,profilaxia' },
      { category: 'Procedimentos', name: 'Restauração', duration_min: 60, buffer_min: 10, price: 250, cost: 45, keywords: 'restauração,obturação,cárie' },
      { category: 'Estética', name: 'Clareamento', duration_min: 60, price: 900, cost: 220, keywords: 'clareamento,branqueamento,dente amarelo' },
      { category: 'Ortodontia', name: 'Manutenção de aparelho', duration_min: 30, price: 150, cost: 20, keywords: 'aparelho,ortodontia,manutenção' },
    ],
  },
  psicologia: {
    label: 'Psicologia',
    terms: T('paciente', 'pacientes', 'psicólogo(a)', 'psicólogos', 'sessão', 'sessões', 'encaminhamento'),
    services: [
      { category: 'Terapias', name: 'Primeira sessão (acolhimento)', duration_min: 50, price: 180, is_entry: 1, package_sessions: 4, package_session_price: 180, sessions_per_week: 1, package_of: 'Sessão de psicoterapia', modality: 'ambos', keywords: 'ansiedade,depressão,terapia,psicólogo,triste,estresse,luto' },
      { category: 'Terapias', name: 'Sessão de psicoterapia', duration_min: 50, price: 180, modality: 'ambos', keywords: 'sessão' },
      { category: 'Terapias', name: 'Terapia de casal', duration_min: 80, price: 280, keywords: 'casal,relacionamento' },
    ],
  },
  fisioterapia: {
    label: 'Fisioterapia',
    terms: T('paciente', 'pacientes', 'fisioterapeuta', 'fisioterapeutas', 'sessão', 'sessões', 'pedido médico'),
    services: [
      { category: 'Avaliações', name: 'Avaliação de fisioterapia', duration_min: 60, price: 120, is_entry: 1, package_sessions: 10, package_session_price: 120, sessions_per_week: 2, requires_document: 1, document_label: 'pedido médico', package_of: 'Sessão de fisioterapia', keywords: 'dor,lombar,coluna,joelho,ombro,fisioterapia,travou,torção,lesão' },
      { category: 'Sessões', name: 'Sessão de fisioterapia', duration_min: 60, price: 120, keywords: 'sessão' },
      { category: 'Sessões', name: 'Pilates clínico', duration_min: 50, price: 90, keywords: 'pilates,alongamento,postura' },
    ],
  },
  estetica: {
    label: 'Estética',
    terms: T('cliente', 'clientes', 'esteticista', 'esteticistas', 'sessão', 'sessões', 'foto da área'),
    services: [
      { category: 'Avaliações', name: 'Avaliação estética', duration_min: 30, price: 0, is_entry: 1, keywords: 'avaliação,manchas,flacidez,celulite,gordura localizada' },
      { category: 'Facial', name: 'Limpeza de pele', duration_min: 60, price: 160, cost: 30, keywords: 'limpeza de pele,cravos,acne' },
      { category: 'Corporal', name: 'Depilação a laser', duration_min: 30, price: 120, cost: 15, keywords: 'depilação,laser,pelos' },
    ],
  },
  veterinaria: {
    label: 'Veterinária / Pet',
    terms: T('tutor', 'tutores', 'veterinário(a)', 'veterinários', 'consulta', 'consultas', 'carteira de vacinação'),
    services: [
      { category: 'Consultas', name: 'Consulta veterinária', duration_min: 30, price: 150, keywords: 'consulta,doente,vomitando,machucado,cachorro,gato' },
      { category: 'Vacinas', name: 'Vacinação', duration_min: 15, price: 90, cost: 35, keywords: 'vacina,vacinação,v10,raiva' },
      { category: 'Estética', name: 'Banho e tosa', duration_min: 60, price: 80, cost: 15, keywords: 'banho,tosa' },
    ],
  },
  generico: {
    label: 'Outro / Genérico',
    terms: T('cliente', 'clientes', 'profissional', 'profissionais', 'atendimento', 'atendimentos', 'documento'),
    services: [{ category: 'Serviços', name: 'Atendimento', duration_min: 60, price: 100, keywords: 'atendimento,agendar,horário' }],
  },
};

export const DEFAULT_HOURS = { 1: ['07:00', '20:00'], 2: ['07:00', '20:00'], 3: ['07:00', '20:00'], 4: ['07:00', '20:00'], 5: ['07:00', '20:00'], 6: ['08:00', '12:00'] };
export const DEFAULT_SCHEDULE = {
  1: [['08:00', '12:00'], ['13:00', '18:00']], 2: [['08:00', '12:00'], ['13:00', '18:00']], 3: [['08:00', '12:00'], ['13:00', '18:00']],
  4: [['08:00', '12:00'], ['13:00', '18:00']], 5: [['08:00', '12:00'], ['13:00', '18:00']],
};
export const termsFor = (tenant) => ({ ...SEGMENTS.generico.terms, ...(SEGMENTS[tenant.segment]?.terms || {}), ...JSON.parse(tenant.terms_json || '{}') });
