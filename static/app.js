/* ============================================================================
   Liquidity & Risk Intelligence — dashboard controller.

   Vanilla, no build step. Every figure on screen comes from the snapshot that
   /api/state serves; this file formats and arranges it and never sums, divides
   or re-projects a balance. Three places look like arithmetic and are not:

     * the runway axis — placing an hours-to-empty value on a fixed 6-hour
       timeline is a drawing coordinate, not a financial figure;
     * "the tightest runway on this track" — a choice between numbers the
       server already sent, never a recomputation of one;
     * the area pressure bar — a ratio of two counts (outlets at risk / outlets
       in the area), never of money.

   A language toggle re-renders the whole page from the same snapshot; alerts
   ship both narrative_bn/narrative_en and parts_bn/parts_en, so nothing is
   left in the wrong language underneath a translated heading.
   ========================================================================== */
(function () {
  'use strict';

  /* ------------------------------------------------------------- constants */

  // The runway timeline runs from now to the operational horizon. This mirrors
  // SETTINGS["alert_horizon_hours"] on the server, which does not publish it in
  // /api/state; it is the extent of the drawing, not a figure. Change it here
  // and on the server together.
  var HORIZON_HOURS = 6;
  // The demand multiplier the "event day" control applies, and the ceiling the
  // /api/simulate endpoint enforces.
  var EVENT_DEMAND = 2.5;
  var DEMAND_MIN = 0.1, DEMAND_MAX = 5.0;
  var MAX_AUDIT_ROWS = 60;
  var TOAST_MS = 4200;

  /* ------------------------------------------------------------------ i18n */

  var STR = {
    bn: {
      /* chrome — keyed to the data-i18n attributes in index.html */
      export: 'এভিডেন্স প্যাক',
      alertQueue: 'সতর্কতা তালিকা',
      runways: 'ব্যালেন্স রানওয়ে',
      cash: 'নগদ টাকা',
      emoney: 'ই-মানি',
      uncertainty: 'সম্ভাব্য সীমা',
      hotspotMap: 'কভারেজ ও হটস্পট',
      areas: 'চাপে থাকা এলাকা',
      network: 'শাখাগুলোর মধ্যে সম্পর্ক',
      whatif: 'কী-হলে',
      audit: 'কেস ইতিহাস',
      appendOnly: 'শুধু সংযোজন',
      footnote: 'শুধুমাত্র পরামর্শমূলক। এখানকার কিছুই কোনো ব্যক্তির বিরুদ্ধে '
        + 'সিদ্ধান্ত দেয় না, কোনো লেনদেন আটকায় না, বা প্রদানকারীদের মধ্যে '
        + 'অর্থ স্থানান্তর করে না। প্রতিটি সংখ্যা একটি সিড-ভিত্তিক সিমুলেশন '
        + 'থেকে গণনা করা হয়েছে; কোনো প্রকৃত ব্যালেন্স বা পরিচয় ব্যবহৃত হয়নি।',

      /* language control */
      langName: 'বাংলা',
      langSwitchTitle: 'ভাষা বদলান',

      /* focus banner */
      verdictAction: 'কার্যক্রম প্রয়োজন',
      verdictWatch: 'নজরে রাখুন',
      verdictNone: 'স্বাভাবিক কার্যক্রম',
      verdictNoAction: 'কোনো ব্যবস্থা নয় — এটিই সঠিক সিদ্ধান্ত',
      openCase: 'এই কেসটি খুলুন',
      storyOutlet: 'আউটলেট',
      storyProvider: 'প্রদানকারী',
      classifierHead: 'কেন কিছু না করাই সঠিক',
      fEmptyTitle: 'এই মুহূর্তে কোনো ফোকাস কেস নেই',
      fEmptyBody: 'সিমুলেশন এখনো কোনো গল্প নির্ধারণ করেনি — নিচের সারি ও তালিকা এখনো সক্রিয়।',
      clAccounts: 'স্বতন্ত্র অ্যাকাউন্ট',
      clTxns: 'লেনদেন',
      clTopShare: 'শীর্ষ অ্যাকাউন্টের অংশ (০–১)',
      clSpread: 'অ্যামাউন্টের বিস্তার (০–১)',
      clContext: 'প্রেক্ষাপট',
      clVerdict: 'সিদ্ধান্ত',

      /* kpi rail */
      kOutlets: 'আউটলেট',
      kAtRisk: 'ঝুঁকিতে আউটলেট',
      kAlerts: 'সতর্কতা',
      kCritical: 'সংকটপূর্ণ',
      kHigh: 'উচ্চ',
      kNeedsReview: 'পর্যালোচনা প্রয়োজন',
      kDataQuality: 'ডেটা গুণমান',
      kOpenCases: 'খোলা কেস',
      kSuppressed: 'স্থগিত পূর্বাভাস',
      kCash: 'নগদ টাকা (নেটওয়ার্ক)',
      kValue: 'মোট মূল্য (নগদ + ই-মানি)',
      kTrackRunway: 'সবচেয়ে কম রানওয়ে',
      kNoDepletion: 'ঘাটতি নেই',
      kTrackClear: 'কোনো ট্র্যাক ৬ ঘণ্টার মধ্যে নেই',
      kInside: '৬ ঘণ্টার মধ্যে',
      kUnitHours: 'ঘণ্টা',

      /* queue */
      qCount: 'সতর্কতা',
      qEmptyTitle: 'এই মুহূর্তে কোনো সতর্কতা নেই',
      qEmptyBody: 'ডেটা গুণমান ও তারল্য—দুই পরীক্ষাই চলছে, কিছু পাওয়া যায়নি।',
      qCritical: 'সংকটপূর্ণ',

      /* detail */
      dEmptyTitle: 'কোনো সতর্কতা নির্বাচন করা হয়নি',
      dEmptyBody: 'বাঁ দিকের তালিকা থেকে একটি সতর্কতা বেছে নিন।',
      pSituation: 'পরিস্থিতি',
      pEvidence: 'প্রমাণ',
      pUncertainty: 'অনিশ্চয়তা',
      pSteps: 'পরবর্তী ধাপ',
      rHead: 'যেসব সম্ভাব্য কারণ বাদ দেওয়া হয়েছে',
      rNone: 'এই কেসে বাদ দেওয়ার মতো কোনো বিকল্প কারণ ছিল না।',
      actionAck: 'স্বীকার করুন',
      actionEscalate: 'উর্ধ্বতনে পাঠান',
      actionResolve: 'নিষ্পত্তি করুন',
      actionNote: 'মন্তব্য যোগ করুন',
      notePh: 'মন্তব্য (ঐচ্ছিক)',
      noteRequired: 'একটি মন্তব্য লিখুন',
      noteLabel: 'মন্তব্য',
      actorPh: 'আপনার নাম / আইডি',
      actorLabel: 'কর্মকর্তা',
      trackLabel: 'প্রদানকারী ট্র্যাক',
      trackAll: 'কেন্দ্রীয় সমন্বয় (সব ট্র্যাক)',
      trackShared: 'শেয়ার্ড ক্যাশ',
      caseHistory: 'এই কেসের ইতিহাস',
      noHistory: 'এখনো কোনো ব্যবস্থা নথিভুক্ত হয়নি।',
      boundaryHead: 'প্রদানকারী সীমা অতিক্রম করা যায়নি।',
      actionRecorded: 'কার্যক্রম নথিভুক্ত হয়েছে',
      actionFailed: 'কার্যক্রম ব্যর্থ হয়েছে',
      srcTemplate: 'টেমপ্লেট থেকে (এলএলএম ব্যবহার হয়নি)',
      srcLlm: 'এলএলএম-সংশোধিত, ক্যাশ করা',

      kvOutlet: 'আউটলেট',
      kvProvider: 'প্রদানকারী',
      kvStatus: 'অবস্থা',
      kvOwner: 'দায়িত্বপ্রাপ্ত ভূমিকা',
      kvAssignee: 'নাম নির্ধারিত',
      kvConfidence: 'আস্থা',
      kvKind: 'ধরন',
      kvCreated: 'তৈরি',
      kvSource: 'বিবরণের সূত্র',

      /* outlets / runways */
      oTotal: 'মোট মূল্য',
      oTxns: 'লেনদেন',
      oReliability: 'নির্ভরযোগ্যতা',
      oAxis: 'রানওয়ে অক্ষ: এখন → ৬ ঘণ্টা',
      oNoTxnTitle: 'এই সময়ে কোনো লেনদেন নেই',
      oNoTxnBody: 'শূন্য লেনদেন মানে শূন্য ব্যালেন্স নয় — কোনো প্রকল্পনা দেখানো হচ্ছে না।',
      oNoPositions: 'কোনো প্রদানকারী অবস্থান পাওয়া যায়নি।',
      cashRow: 'নগদ টাকা',
      depleted: 'নিঃশেষিত',
      suppressedTag: 'ফিড যাচাই হয়নি',
      noDepletion: 'ঘাটতির পূর্বাভাস নেই',
      verifyFeed: 'যাচাই করুন',
      beyondHorizon: '৬ ঘণ্টার বাইরে',
      lowConf: 'কম আস্থা',
      unitHoursShort: 'ঘ',
      feedFresh: 'তাজা',
      feedDelayed: 'দেরি',
      feedStale: 'বিলম্বিত',
      feedConflicting: 'পরস্পরবিরোধী',
      feedMissing: 'ফিড নেই',
      feedAge: 'মিনিট আগে',
      noProjection: '—',

      /* map */
      mapEmptyTitle: 'কোনো আউটলেট নেই',
      mapEmptyBody: 'মানচিত্র আঁকতে অন্তত একটি আউটলেট প্রয়োজন।',
      mapAreas: 'এলাকা',
      mapAtRisk: 'ঝুঁকিতে',
      mapWorst: 'সর্বাধিক চাপ',
      mapAlt: 'আউটলেট মানচিত্র',

      /* areas table */
      thArea: 'এলাকা',
      thOutlets: 'আউটলেট',
      thAtRisk: 'ঝুঁকিতে',
      thCash: 'নগদ',
      thEmoney: 'ই-মানি',
      thPressure: 'চাপ',
      areasEmptyTitle: 'কোনো এলাকা পাওয়া যায়নি',
      areasEmptyBody: 'এলাকাভিত্তিক চাপ দেখানোর মতো তথ্য নেই।',

      /* support */
      supportHead: 'কাছাকাছি সহায়তার প্রস্তাব',
      supportEmpty: 'এই মুহূর্তে সমন্বয়ের কোনো প্রস্তাব নেই।',
      supportNeeds: 'সহায়তা প্রয়োজন',
      supportFrom: 'উৎস',
      supportHeadroom: 'সুযোগ',
      supportDistance: 'দূরত্ব',
      supportSameArea: 'একই এলাকা',
      supportOtherArea: 'ভিন্ন এলাকা',
      supportKm: 'কিমি',

      /* network */
      netEmptyTitle: 'কোনো সম্পর্ক পাওয়া যায়নি',
      netEmptyBody: '৩+ শাখায় দেখা যাওয়া অ্যাকাউন্ট নেই।',
      netSharedAccounts: 'ভাগ করা অ্যাকাউন্ট',
      netConcentrated: 'কেন্দ্রীভূত',
      netLinks: 'সংযোগ',
      netAlt: 'শাখাগুলোর সম্পর্কের গ্রাফ',
      netCross: 'একাধিক প্রদানকারীতে সক্রিয় অ্যাকাউন্ট',
      netLabels: 'লাল শাখা = কেন্দ্রীভূত অ্যাকাউন্ট রয়েছে',

      /* what-if */
      wiDemand: 'চাহিদার গুণক',
      wiEvent: 'ঈদের দিন (ইভেন্ট)',
      wiRun: 'আবার চালান',
      wiApplied: 'প্রয়োগ করা হয়েছে',
      wiHint: 'এই স্লাইডারটি সার্ভারে নতুন সিমুলেশন চালায় — শুধু দেখা নয়, '
        + 'নেটওয়ার্কটি আবার গণনা হয়।',
      wiEmpty: 'সিমুলেশন নিয়ন্ত্রণ পাওয়া যায়নি।',
      wiRerun: 'নতুন করে গণনা করা হচ্ছে…',

      /* metrics */
      metricsEmpty: 'কোনো পরিমাপ পাওয়া যায়নি।',
      mEpisodes: 'গ্রাউন্ড-ট্রুথ এপিসোড',
      mExpected: 'প্রত্যাশিত ফাইন্ডিং',
      mDetected: 'শনাক্ত হয়েছে',
      mTP: 'সত্য ধনাত্মক',
      mFP: 'মিথ্যা ধনাত্মক',
      mFN: 'মিথ্যা ঋণাত্মক',
      mPrecision: 'প্রিসিশন (পরিমাপকৃত)',
      mRecall: 'রিকল (পরিমাপকৃত)',
      mFPR: 'মিথ্যা ধনাত্মক হার',
      mSpike: 'চাহিদা-বৃদ্ধির এপিসোড',
      mNeedsReview: 'পর্যালোচনার সতর্কতা',

      /* audit */
      auditEmptyTitle: 'ইতিহাস খালি',
      auditEmptyBody: 'এখনো কোনো কেস কার্যক্রম নথিভুক্ত হয়নি।',
      auditTruncated: 'সর্বশেষ {shown}টি দেখানো হচ্ছে (মোট {total}টি) — পূর্ণ '
        + 'ইতিহাস /api/cases-এ আছে।',

      /* misc */
      unknown: 'অজানা',
      notProjected: 'পূর্বাভাস নেই',
      loadFailed: 'ডেটা লোড করা যায়নি',
      retry: 'আবার চেষ্টা করুন',
      queueLabel: 'সতর্কতার তালিকা — তীর চিহ্ন দিয়ে চলুন',
      langChanged: 'ভাষা: বাংলা',
      scenarioChanged: 'সিনারিও বদলানো হয়েছে',

      sevCritical: 'সংকটপূর্ণ',
      sevHigh: 'উচ্চ',
      sevMedium: 'মধ্যম',
      sevLow: 'নিম্ন',
      kindLiquidity: 'তারল্য',
      kindAnomaly: 'অস্বাভাবিক ধারা',
      kindDataQuality: 'ডেটা গুণমান',
      kindCoordination: 'সমন্বয়',
      clsNormal: 'স্বাভাবিক',
      clsNeedsReview: 'পর্যালোচনা প্রয়োজন',
      clsDataQuality: 'ডেটা গুণমান',
      clsDemandSpike: 'চাহিদার স্বাভাবিক বৃদ্ধি',
      stNew: 'নতুন',
      stAcknowledged: 'স্বীকৃত',
      stEscalated: 'উর্ধ্বতনে',
      stResolved: 'নিষ্পত্তি',
      roleAgent: 'এজেন্ট',
      roleFieldOfficer: 'ফিল্ড অফিসার',
      roleAreaManager: 'এরিয়া ম্যানেজার',
      roleCentralOps: 'কেন্দ্রীয় অপারেশনস',
      roleRiskAnalyst: 'ঝুঁকি বিশ্লেষক',
      ctxOrdinary: 'সাধারণ দিন',
      ctxEid: 'ঈদ',
      ctxSalary: 'বেতন দিবস'
    },
    en: {
      export: 'Evidence pack',
      alertQueue: 'Alert queue',
      runways: 'Balance runways',
      cash: 'Cash',
      emoney: 'E-money',
      uncertainty: 'Estimate range',
      hotspotMap: 'Coverage & hotspots',
      areas: 'Areas by pressure',
      network: 'Cross-outlet relationships',
      whatif: 'What-if',
      audit: 'Case history',
      appendOnly: 'append-only',
      footnote: 'Advisory only. Nothing here determines wrongdoing, blocks a '
        + 'transaction, or moves value between providers. Every figure is '
        + 'computed from a seeded simulation; no real balances or identities '
        + 'are used.',

      langName: 'English',
      langSwitchTitle: 'Switch language',

      verdictAction: 'Action expected',
      verdictWatch: 'Watch',
      verdictNone: 'Ordinary operations',
      verdictNoAction: 'No action — which is the correct answer',
      openCase: 'Open this case',
      storyOutlet: 'Outlet',
      storyProvider: 'Provider',
      classifierHead: 'Why doing nothing is correct',
      fEmptyTitle: 'No focus case right now',
      fEmptyBody: 'The simulation has not named a story yet — the rows and lists below are still live.',
      clAccounts: 'Distinct accounts',
      clTxns: 'Transactions',
      clTopShare: 'Top-account share (0-1)',
      clSpread: 'Amount spread (0-1)',
      clContext: 'Context',
      clVerdict: 'Verdict',

      kOutlets: 'Outlets',
      kAtRisk: 'Outlets at risk',
      kAlerts: 'Alerts',
      kCritical: 'Critical',
      kHigh: 'High',
      kNeedsReview: 'Needs review',
      kDataQuality: 'Data quality',
      kOpenCases: 'Open cases',
      kSuppressed: 'Withheld projections',
      kCash: 'Cash (network)',
      kValue: 'Total value (cash + e-money)',
      kTrackRunway: 'shortest runway',
      kNoDepletion: 'no depletion',
      kTrackClear: 'no track inside 6h',
      kInside: 'inside 6h',
      kUnitHours: 'hours',

      qCount: 'alerts',
      qEmptyTitle: 'No alerts right now',
      qEmptyBody: 'Both detectors are running across the network and found nothing.',
      qCritical: 'critical',

      dEmptyTitle: 'No alert selected',
      dEmptyBody: 'Choose an alert from the queue on the left.',
      pSituation: 'Situation',
      pEvidence: 'Evidence',
      pUncertainty: 'Uncertainty',
      pSteps: 'Next steps',
      rHead: 'Hypotheses considered and set aside',
      rNone: 'No alternative hypothesis had to be set aside for this case.',
      actionAck: 'Acknowledge',
      actionEscalate: 'Escalate',
      actionResolve: 'Resolve',
      actionNote: 'Add note',
      notePh: 'Note (optional)',
      noteRequired: 'Add a note first',
      noteLabel: 'Note',
      actorPh: 'your name / id',
      actorLabel: 'Actor',
      trackLabel: 'Provider track',
      trackAll: 'Central oversight (all tracks)',
      trackShared: 'shared cash',
      caseHistory: 'History of this case',
      noHistory: 'No action recorded yet.',
      boundaryHead: 'Provider boundary not crossed.',
      actionRecorded: 'Action recorded',
      actionFailed: 'Action failed',
      srcTemplate: 'from template (LLM layer not used)',
      srcLlm: 'LLM-rephrased, cached',

      kvOutlet: 'Outlet',
      kvProvider: 'Provider',
      kvStatus: 'Status',
      kvOwner: 'Owner role',
      kvAssignee: 'Named assignee',
      kvConfidence: 'Confidence',
      kvKind: 'Kind',
      kvCreated: 'Created',
      kvSource: 'Narrative source',

      oTotal: 'total value',
      oTxns: 'transactions',
      oReliability: 'Reliability',
      oAxis: 'Runway axis: now to 6 hours',
      oNoTxnTitle: 'No transactions in this window',
      oNoTxnBody: 'Zero transactions is not zero balance — no projection is shown.',
      oNoPositions: 'No provider positions available.',
      cashRow: 'Cash',
      depleted: 'Depleted',
      suppressedTag: 'Feed unverified',
      noDepletion: 'No depletion projected',
      verifyFeed: 'verify',
      beyondHorizon: 'beyond 6h',
      lowConf: 'low confidence',
      unitHoursShort: 'h',
      feedFresh: 'fresh',
      feedDelayed: 'delayed',
      feedStale: 'stale',
      feedConflicting: 'conflicting',
      feedMissing: 'missing',
      feedAge: 'min ago',
      noProjection: 'n/a',

      mapEmptyTitle: 'No outlets to map',
      mapEmptyBody: 'At least one outlet is needed to draw the coverage map.',
      mapAreas: 'areas',
      mapAtRisk: 'at risk',
      mapWorst: 'worst area',
      mapAlt: 'Map of outlets and hotspot areas',

      thArea: 'Area',
      thOutlets: 'Outlets',
      thAtRisk: 'At risk',
      thCash: 'Cash',
      thEmoney: 'E-money',
      thPressure: 'Pressure',
      areasEmptyTitle: 'No areas found',
      areasEmptyBody: 'Nothing to rank by pressure in this snapshot.',

      supportHead: 'Nearby support suggestions',
      supportEmpty: 'No coordination suggestion right now.',
      supportNeeds: 'needs support',
      supportFrom: 'from',
      supportHeadroom: 'headroom',
      supportDistance: 'distance',
      supportSameArea: 'same area',
      supportOtherArea: 'different area',
      supportKm: 'km',

      netEmptyTitle: 'No relationships found',
      netEmptyBody: 'No account appears at 3 or more outlets in this snapshot.',
      netSharedAccounts: 'shared accounts',
      netConcentrated: 'concentrated',
      netLinks: 'links',
      netAlt: 'Graph of relationships between outlets',
      netCross: 'accounts active on more than one provider',
      netLabels: 'red outlet = hosts a concentrated account',

      wiDemand: 'Demand multiplier',
      wiEvent: 'Event day (Eid)',
      wiRun: 'Re-run',
      wiApplied: 'Applied',
      wiHint: 'This slider runs a new simulation on the server — the network is '
        + 'recomputed, not just re-drawn.',
      wiEmpty: 'Simulation controls unavailable.',
      wiRerun: 'recomputing…',

      metricsEmpty: 'No measurements available.',
      mEpisodes: 'Ground-truth episodes',
      mExpected: 'Expected findings',
      mDetected: 'Detected',
      mTP: 'True positives',
      mFP: 'False positives',
      mFN: 'False negatives',
      mPrecision: 'Precision (measured)',
      mRecall: 'Recall (measured)',
      mFPR: 'False-positive rate',
      mSpike: 'Demand-spike episodes',
      mNeedsReview: 'Needs-review alerts',

      auditEmptyTitle: 'Nothing recorded yet',
      auditEmptyBody: 'No case action has been logged.',
      auditTruncated: 'Showing the most recent {shown} of {total} — the full '
        + 'trail is at /api/cases.',

      unknown: 'unknown',
      notProjected: 'not projected',
      loadFailed: 'Could not load the snapshot',
      retry: 'Try again',
      queueLabel: 'Alert queue — use the arrow keys to move',
      langChanged: 'Language: English',
      scenarioChanged: 'Scenario changed',

      sevCritical: 'critical',
      sevHigh: 'high',
      sevMedium: 'medium',
      sevLow: 'low',
      kindLiquidity: 'Liquidity',
      kindAnomaly: 'Unusual pattern',
      kindDataQuality: 'Data quality',
      kindCoordination: 'Coordination',
      clsNormal: 'normal',
      clsNeedsReview: 'needs review',
      clsDataQuality: 'data quality',
      clsDemandSpike: 'demand spike',
      stNew: 'new',
      stAcknowledged: 'acknowledged',
      stEscalated: 'escalated',
      stResolved: 'resolved',
      roleAgent: 'agent',
      roleFieldOfficer: 'field officer',
      roleAreaManager: 'area manager',
      roleCentralOps: 'central operations',
      roleRiskAnalyst: 'risk analyst',
      ctxOrdinary: 'ordinary day',
      ctxEid: 'Eid',
      ctxSalary: 'salary day'
    }
  };

  var SEV_CLASS = { critical: 'sev-critical', high: 'sev-high',
                    medium: 'sev-medium', low: 'sev-low' };
  var CLS_TAG = { needs_review: 'review', data_quality: 'dq',
                  demand_spike: 'spike', coordination: 'coord' };
  // Feed health reuses the tag palette so a degraded feed is visibly not
  // fresh: amber for a feed that is merely late (delayed, stale), red for one
  // that cannot be trusted at all (conflicting, missing), no badge for fresh.
  // The two states sharing a colour are told apart by their label and the age
  // beside it, which is the part a user actually reads.
  var FEED_TAG = { delayed: 'dq', stale: 'dq',
                   conflicting: 'review', missing: 'review' };

  /* ------------------------------------------------------- state + helpers */

  var state = {
    lang: 'bn',
    snapshot: null,
    alerts: [],
    cases: [],
    casesError: null,
    history: {},          // alert id -> audit events for that case
    selectedId: null,
    detailKey: '',
    busy: false,
    fatal: null,
    demand: 1.0,
    detailToken: 0
  };

  function t(key) {
    var table = STR[state.lang] || STR.en;
    return table[key] != null ? table[key] : (STR.en[key] != null ? STR.en[key] : key);
  }

  function $(sel) { return document.querySelector(sel); }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function finite(value) {
    return typeof value === 'number' && isFinite(value);
  }

  var BN_DIGITS = { '0': '০', '1': '১', '2': '২', '3': '৩', '4': '৪',
                    '5': '৫', '6': '৬', '7': '৭', '8': '৮', '9': '৯' };

  function digits(text) {
    return state.lang === 'bn' ? String(text).replace(/[0-9]/g, function (d) {
      return BN_DIGITS[d];
    }) : String(text);
  }

  // The server formats with Python's f"{x:,.Nf}". On an exact tie Python rounds
  // to the even digit and JS rounds away from zero, so the same balance could
  // print two ways — once in a panel, once inside a narrative sentence. The two
  // agree on everything else, so only a true tie is special-cased.
  //
  // Deciding "is this a tie" on the float product is not reliable: 0.35 x 10
  // rounds to exactly 3.5, yet 0.35 is not a tie (its exact value is
  // 0.34999…). So the test reads the exact decimal expansion, which toFixed(30)
  // gives for any figure this dashboard shows; a tie means a single 5 followed
  // by nothing but zeros.
  function isTie(value, decimals) {
    var text = value.toFixed(30);
    var frac = text.indexOf('.') === -1 ? '' : text.slice(text.indexOf('.') + 1);
    if (frac.length <= decimals) return false;
    if (frac.charAt(decimals) !== '5') return false;
    for (var i = decimals + 1; i < frac.length; i++) {
      if (frac.charAt(i) !== '0') return false;
    }
    return true;
  }

  function fixedString(value, decimals) {
    var text = value.toFixed(decimals);
    if (!isTie(value, decimals)) return text;
    var k = Math.floor(value * Math.pow(10, decimals));
    if (k % 2 !== 0) k += 1;                 // half-even picks the even digit
    var out = String(Math.abs(k));
    if (decimals > 0) {
      while (out.length <= decimals) out = '0' + out;
      out = out.slice(0, out.length - decimals) + '.' + out.slice(out.length - decimals);
    }
    return (k < 0 ? '-' : '') + out;
  }

  function group(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  // Grouping matches the server's format_bdt / format_hours exactly, so a
  // figure in the UI and the same figure inside a narrative never disagree.
  function fBdt(value) {
    if (!finite(value)) return t('unknown');
    return '৳' + digits(group(fixedString(value, 0)));
  }

  function fInt(value) {
    if (!finite(value)) return t('unknown');
    return digits(group(fixedString(value, 0)));
  }

  function fHours(value) {
    if (!finite(value)) return t('unknown');
    return digits(fixedString(value, 1));
  }

  function fRatio(value) {
    if (!finite(value)) return t('unknown');
    return digits(fixedString(value, 2));
  }

  function fKm(value) {
    if (!finite(value)) return t('unknown');
    return digits(fixedString(value, 1));
  }

  function fTime(ts) {
    if (!finite(ts)) return t('unknown');
    var d = new Date(ts * 1000);
    var hh = String(d.getHours()); if (hh.length < 2) hh = '0' + hh;
    var mm = String(d.getMinutes()); if (mm.length < 2) mm = '0' + mm;
    var ss = String(d.getSeconds()); if (ss.length < 2) ss = '0' + ss;
    return digits(hh + ':' + mm + ':' + ss);
  }

  function isoTime(ts) {
    return finite(ts) ? new Date(ts * 1000).toISOString() : '';
  }

  function cls(map, key, fallback) {
    return map[key] || fallback || '';
  }

  /* ----------------------------------------------------------- small parts */

  function svgIcon(paths) {
    return '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">'
      + paths + '</svg>';
  }

  var ICON = {
    check: '<path d="M4 12.5 9 17.5 20 6.5"/>',
    up: '<path d="M12 20V5m0 0-5 5m5-5 5 5"/>',
    done: '<path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"/>'
      + '<path d="M8.5 12.5 11 15l4.5-5"/>',
    note: '<path d="M4 20h4l10-10-4-4L4 16v4Z"/><path d="M14 6l4 4"/>',
    run: '<path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4h-4"/>',
    open: '<path d="M5 12h13m0 0-5-5m5 5-5 5"/>'
  };

  function emptyBlock(title, body) {
    return '<div class="empty"><strong>' + esc(title) + '</strong>'
      + esc(body) + '</div>';
  }

  function tag(key, text) {
    return '<span class="tag ' + key + '">' + esc(text) + '</span>';
  }

  function sevLabel(sev) {
    return t('sev' + String(sev || '').charAt(0).toUpperCase()
      + String(sev || '').slice(1));
  }

  function kindLabel(kind) {
    var key = 'kind' + String(kind || '').split('_').map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join('');
    return t(key);
  }

  function statusLabel(status) {
    var key = 'st' + String(status || '').split('_').map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join('');
    return t(key);
  }

  function roleLabel(role) {
    var key = 'role' + String(role || '').split('_').map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join('');
    var value = t(key);
    return value === key ? String(role || '') : value;
  }

  function clsLabel(classification) {
    var key = 'cls' + String(classification || '').split('_').map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join('');
    var value = t(key);
    return value === key ? String(classification || '') : value;
  }

  function providerName(pid, positions) {
    if (!pid) return t('trackShared');
    var list = positions || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].provider_id === pid) {
        return state.lang === 'bn' ? (list[i].name_bn || list[i].name) : list[i].name;
      }
    }
    return pid;
  }

  function feedLabel(status) {
    if (status === 'fresh') return t('feedFresh');
    if (status === 'delayed') return t('feedDelayed');
    if (status === 'stale') return t('feedStale');
    if (status === 'conflicting') return t('feedConflicting');
    if (status === 'missing') return t('feedMissing');
    return String(status || t('unknown'));
  }

  function ctxLabel(ctx) {
    if (ctx === 'eid') return t('ctxEid');
    if (ctx === 'salary_day') return t('ctxSalary');
    return t('ctxOrdinary');
  }

  /* --------------------------------------------------------------- network */

  function api(path, options) {
    return fetch(path, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (body) {
        if (!res.ok) {
          var err = new Error((body && body.detail) || ('HTTP ' + res.status));
          err.status = res.status;
          err.detail = body && body.detail;
          err.boundary = body && body.boundary;
          throw err;
        }
        return body;
      });
    });
  }

  function postJson(path, payload) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  }

  var reduceMotion = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;

  // Animation is opt-in per call and fully skipped under the OS setting. Only
  // one-shot opacity settles are used: no loops, no spinners, no parallax.
  function fadeIn(node, ms) {
    if (!node || (reduceMotion && reduceMotion.matches)) return;
    if (typeof node.animate !== 'function') return;
    node.animate([{ opacity: 0 }, { opacity: 1 }],
                 { duration: ms || 180, easing: 'cubic-bezier(.32,.72,.32,1)',
                   iterations: 1 });
  }

  var toastTimer = null;
  function toast(message, isError) {
    var node = $('#toast');
    if (!node) return;
    node.textContent = message;
    node.className = isError ? 'toast error show' : 'toast show';
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      node.className = 'toast' + (isError ? ' error' : '');
    }, TOAST_MS);
  }

  /* ------------------------------------------------------------ rendering */

  function applyI18n() {
    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      var key = nodes[i].getAttribute('data-i18n');
      var value = STR[state.lang][key];
      if (value != null) nodes[i].textContent = value;
    }
    var toggle = $('#lang-toggle');
    if (toggle) {
      toggle.setAttribute('aria-pressed', state.lang === 'bn' ? 'true' : 'false');
      toggle.setAttribute('title', t('langSwitchTitle'));
    }
    var label = $('#lang-label');
    if (label) label.textContent = t('langName');
    document.documentElement.setAttribute('data-lang', state.lang);
    document.documentElement.setAttribute('lang', state.lang);
  }

  function renderFocus() {
    var host = $('#focus');
    var focus = state.snapshot && state.snapshot.focus;
    if (!host) return;
    if (!focus) {
      // A missing focus is a state to show, not a panel to leave blank.
      host.innerHTML = emptyBlock(t('fEmptyTitle'), t('fEmptyBody'));
      return;
    }

    var verdictKey = focus.expectation === 'action' ? 'act'
      : focus.expectation === 'no_action' ? 'noop'
        : focus.expectation === 'watch' ? 'noop' : 'ok';
    var verdictText = focus.expectation === 'action' ? t('verdictAction')
      : focus.expectation === 'no_action' ? t('verdictNoAction')
        : focus.expectation === 'watch' ? t('verdictWatch') : t('verdictNone');

    var html = '<h2>' + esc(focus.title) + '</h2><p>' + esc(focus.blurb) + '</p>';
    html += '<div class="q-top"><span class="verdict ' + verdictKey + '">'
      + esc(verdictText) + '</span>';
    if (focus.alert_id) {
      html += '<button class="btn btn-act primary" type="button" data-open-alert="'
        + esc(focus.alert_id) + '">' + svgIcon(ICON.open)
        + '<span>' + esc(t('openCase')) + '</span></button>';
    }
    html += '</div>';

    if (focus.outlet_id || focus.provider_id) {
      var where = [];
      if (focus.outlet_id) where.push(t('storyOutlet') + ': ' + focus.outlet_id);
      if (focus.provider_id) {
        where.push(t('storyProvider') + ': '
          + providerName(focus.provider_id, positionsOf(focus.outlet_id)));
      }
      html += '<p class="kv">' + esc(where.join(' · ')) + '</p>';
    }

    var clf = focus.classifier;
    if (clf && clf.accounts != null) {
      html += '<div class="metrics"><div class="m-row"><span>'
        + esc(t('classifierHead')) + '</span><b>' + esc(String(clf.verdict || ''))
        + '</b></div>';
      html += metricRow(t('clAccounts'), fInt(clf.accounts));
      html += metricRow(t('clTxns'), fInt(clf.txns));
      html += metricRow(t('clTopShare'), fRatio(clf.top_account_share));
      html += metricRow(t('clSpread'), fRatio(clf.amount_spread));
      html += metricRow(t('clContext'), ctxLabel(clf.calendar_context));
      html += metricRow(t('clVerdict'), String(clf.verdict || ''));
      html += '</div>';
      if (clf.explanation) html += '<p class="hint">' + esc(clf.explanation) + '</p>';
    }
    host.innerHTML = html;
  }

  function positionsOf(outletId) {
    var outlets = (state.snapshot && state.snapshot.outlets) || [];
    for (var i = 0; i < outlets.length; i++) {
      if (outlets[i].id === outletId) return outlets[i].positions || [];
    }
    return [];
  }

  function kpiCell(label, valueHtml, cls, sub) {
    // dt/dd inside a real dl keeps this a description list for AT; the inline
    // margin reset is the one place the CSS has no hook for the UA's dl margin.
    return '<div class="kpi' + (cls ? ' ' + cls : '') + '">'
      + '<dl style="margin:0"><dt>' + esc(label) + '</dt>'
      + '<dd>' + valueHtml + '</dd>'
      + (sub ? '<dd><span class="hint">' + sub + '</span></dd>' : '')
      + '</dl></div>';
  }

  // The worst runway on a track. This picks the smallest hours-to-empty the
  // server already computed for that track; it never derives a figure.
  function trackWorst(providerId) {
    var outlets = (state.snapshot && state.snapshot.outlets) || [];
    var best = null;
    var inside = 0;
    for (var i = 0; i < outlets.length; i++) {
      var outlet = outlets[i];
      if (providerId === null) {
        if (finite(outlet.cash_hours)) {
          if (outlet.cash_hours <= HORIZON_HOURS) inside++;
          if (!best || outlet.cash_hours < best.hours) {
            best = { hours: outlet.cash_hours, outlet: outlet,
                     balance: outlet.cash, confidence: outlet.cash_confidence };
          }
        }
      } else {
        var list = outlet.positions || [];
        for (var j = 0; j < list.length; j++) {
          var pos = list[j];
          if (pos.provider_id !== providerId || pos.suppressed) continue;
          if (finite(pos.hours_to_empty)) {
            if (pos.hours_to_empty <= HORIZON_HOURS) inside++;
            if (!best || pos.hours_to_empty < best.hours) {
              best = { hours: pos.hours_to_empty, outlet: outlet,
                       balance: pos.balance, confidence: pos.confidence };
            }
          }
        }
      }
    }
    return { worst: best, inside: inside };
  }

  function renderKpis() {
    var host = $('#kpis');
    if (!host || !state.snapshot) return;
    var s = state.snapshot.summary || {};
    var html = '';

    html += kpiCell(t('kOutlets'), fInt(s.outlets), '');
    html += kpiCell(t('kAtRisk'), fInt(s.at_risk_outlets),
                    s.at_risk_outlets > 0 ? 'is-alert' : 'is-ok');
    html += kpiCell(t('kAlerts'), fInt(s.alerts), '');
    html += kpiCell(t('kCritical'), fInt(s.critical), s.critical > 0 ? 'is-alert' : 'is-ok');
    html += kpiCell(t('kHigh'), fInt(s.high), s.high > 0 ? 'is-warn' : 'is-ok');
    html += kpiCell(t('kNeedsReview'), fInt(s.needs_review),
                    s.needs_review > 0 ? 'is-warn' : 'is-ok');
    html += kpiCell(t('kDataQuality'), fInt(s.data_quality),
                    s.data_quality > 0 ? 'is-warn' : 'is-ok');
    html += kpiCell(t('kOpenCases'), fInt(s.open_cases), '');
    html += kpiCell(t('kSuppressed'), fInt(s.suppressed_projections),
                    s.suppressed_projections > 0 ? 'is-warn' : 'is-ok');

    // The two blended totals sit immediately beside the per-track panel, which
    // is the point: an aggregate can look comfortable while one track is hours
    // from exhaustion, so the composition is never off-screen from the total.
    html += kpiCell(t('kCash'), fBdt(s.total_cash), 'is-cash');
    html += kpiCell(t('kValue'), fBdt(s.total_value), 'is-float');

    var track = trackWorst(null);
    html += trackCell(t('cashRow'), track, 'is-cash');

    var providers = providerList();
    for (var i = 0; i < providers.length; i++) {
      html += trackCell(providerLabel(providers[i]), trackWorst(providers[i].id),
                        'is-float');
    }

    host.innerHTML = html;
  }

  // One entry per provider id, with the bilingual names the snapshot carries on
  // every position. Same tracks in every outlet, so the first sighting wins.
  function providerList() {
    var outlets = (state.snapshot && state.snapshot.outlets) || [];
    var seen = [];
    var index = {};
    for (var i = 0; i < outlets.length; i++) {
      var list = outlets[i].positions || [];
      for (var j = 0; j < list.length; j++) {
        var pos = list[j];
        if (index[pos.provider_id]) continue;
        index[pos.provider_id] = true;
        seen.push({ id: pos.provider_id, name: pos.name, name_bn: pos.name_bn });
      }
    }
    return seen;
  }

  function providerLabel(entry) {
    return state.lang === 'bn' ? (entry.name_bn || entry.name) : entry.name;
  }

  function trackCell(name, track, identityClass) {
    var worst = track.worst;
    var cls = 'is-ok';
    if (!worst) {
      cls = identityClass;
    } else if (worst.hours <= HORIZON_HOURS * 0.25) {
      cls = 'is-alert';
    } else if (worst.hours <= HORIZON_HOURS) {
      cls = 'is-warn';
    } else {
      cls = identityClass;
    }
    var value;
    if (!worst) {
      value = '<span class="hint">' + esc(t('kTrackClear')) + '</span>';
    } else {
      value = fHours(worst.hours) + '<span class="unit">'
        + esc(t('unitHoursShort')) + '</span>';
    }
    var sub = '';
    if (worst) {
      sub = esc(worst.outlet.name + ' · ' + fBdt(worst.balance) + ' · '
        + t('kInside') + ': ' + fInt(track.inside));
    }
    return kpiCell(name + ' — ' + t('kTrackRunway'), value, cls, sub);
  }

  function renderQueue() {
    var host = $('#queue');
    var count = $('#queue-count');
    if (!host) return;
    var alerts = state.alerts || [];
    if (count) {
      count.textContent = fInt(alerts.length) + ' ' + t('qCount')
        + (state.snapshot && state.snapshot.summary
          ? ' · ' + fInt(state.snapshot.summary.critical) + ' ' + t('qCritical')
          : '');
    }
    host.setAttribute('aria-label', t('queueLabel'));

    if (!alerts.length) {
      host.innerHTML = emptyBlock(t('qEmptyTitle'), t('qEmptyBody'));
      return;
    }

    var html = '';
    for (var i = 0; i < alerts.length; i++) {
      var a = alerts[i];
      var sev = SEV_CLASS[a.severity] || 'sev-medium';
      var selected = a.id === state.selectedId;
      var positions = positionsOf(a.outlet_id);
      var title = a.outlet_id + ' · ' + providerName(a.provider_id, positions);
      var sub = reasonFor(a);
      html += '<div role="listitem">'
        + '<button class="q-item ' + sev + '" type="button" data-alert="'
        + esc(a.id) + '"' + (selected ? ' aria-current="true"' : '') + '>'
        + '<div class="q-top">'
        + '<span class="q-sev">' + esc(sevLabel(a.severity)) + '</span>'
        + '<span class="q-kind">' + esc(kindLabel(a.kind)) + '</span>'
        + (CLS_TAG[a.classification] ? tag(CLS_TAG[a.classification],
            clsLabel(a.classification)) : '')
        + '<span class="tag">' + esc(statusLabel(a.status)) + '</span>'
        + '</div>'
        + '<div class="q-title">' + esc(title) + '</div>'
        + '<div class="q-sub">' + esc(sub) + '</div>'
        + '</button></div>';
    }
    host.innerHTML = html;
  }

  function reasonFor(alert) {
    return alert.reason || t('unknown');
  }

  function renderDetail() {
    var host = $('#detail');
    if (!host || !state.snapshot) return;

    var alert = null;
    for (var i = 0; i < state.alerts.length; i++) {
      if (state.alerts[i].id === state.selectedId) { alert = state.alerts[i]; break; }
    }

    if (!alert) {
      var key = 'none|' + state.lang;
      if (state.detailKey === key) return;
      state.detailKey = key;
      host.innerHTML = emptyBlock(t('dEmptyTitle'), t('dEmptyBody'));
      return;
    }

    var history = state.history[alert.id] || [];
    var key = state.lang + '|' + alert.id + '|' + history.length + '|'
      + JSON.stringify(alert);
    if (state.detailKey === key) return;
    state.detailKey = key;

    var parts = (state.lang === 'bn' ? alert.parts_bn : alert.parts_en) || {};
    var positions = positionsOf(alert.outlet_id);
    var outlet = outletById(alert.outlet_id);

    var html = '<div class="d-head ' + (SEV_CLASS[alert.severity] || 'sev-medium') + '">'
      + '<h3>' + esc(kindLabel(alert.kind)) + ' · ' + esc(alert.outlet_id) + '</h3>'
      + '<span class="q-sev">' + esc(sevLabel(alert.severity)) + '</span>'
      + '</div>';

    html += '<div class="d-meta">'
      + kv(t('kvOutlet'), (outlet ? outlet.name : '') + ' (' + alert.outlet_id + ')')
      + kv(t('kvProvider'), providerName(alert.provider_id, positions))
      + kv(t('kvStatus'), statusLabel(alert.status))
      + kv(t('kvOwner'), roleLabel(alert.owner) || t('unknown'))
      + kv(t('kvAssignee'), alert.assignee || t('unknown'))
      + kv(t('kvConfidence'), fRatio(alert.confidence))
      + kv(t('kvCreated'), fTime(alert.created_at))
      + kv(t('kvSource'), alert.narrative_source === 'llm-cached'
          ? t('srcLlm') : t('srcTemplate'))
      + (CLS_TAG[alert.classification]
          ? '<span class="kv">' + esc(t('kvKind')) + ': '
            + tag(CLS_TAG[alert.classification], clsLabel(alert.classification))
            + '</span>'
          : '')
      + '</div>';

    // "Why flagged" leads: the rejected hypotheses are the reason a case is
    // reviewable rather than actionable, so they sit above the narrative parts
    // instead of trailing them.
    html += rejectedBlock(alert, parts);

    html += '<div class="parts">';
    html += part('situation', t('pSituation'), paragraphs(parts.situation));
    html += part('evidence', t('pEvidence'), listBlock(parts.evidence));
    html += part('uncertainty', t('pUncertainty'), paragraphs(parts.uncertainty));
    html += part('steps', t('pSteps'), listBlock(parts.next_steps || alert.recommended_steps));
    html += '</div>';

    html += actionsBlock(alert);
    html += historyBlock(history, alert);

    host.innerHTML = html;
  }

  function outletById(id) {
    var outlets = (state.snapshot && state.snapshot.outlets) || [];
    for (var i = 0; i < outlets.length; i++) if (outlets[i].id === id) return outlets[i];
    return null;
  }

  function kv(label, value) {
    return '<span class="kv">' + esc(label) + ': <b>' + esc(value) + '</b></span>';
  }

  function paragraphs(text) {
    var lines = String(text == null ? '' : text).split('\n');
    var out = '';
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].trim()) out += '<p>' + esc(lines[i].trim()) + '</p>';
    }
    return out || '<p>' + esc(t('unknown')) + '</p>';
  }

  function listBlock(items) {
    if (!items || !items.length) return '<p>' + esc(t('unknown')) + '</p>';
    var out = '<ul>';
    for (var i = 0; i < items.length; i++) out += '<li>' + esc(items[i]) + '</li>';
    return out + '</ul>';
  }

  function part(cls, heading, body) {
    return '<div class="part ' + cls + '"><h4>' + esc(heading) + '</h4>' + body + '</div>';
  }

  // The rejection block is the product's differentiator, so it is rendered as
  // its own weighted panel rather than a footnote. The English pairs arrive
  // structured; the Bengali rejections arrive only as pre-rendered lines, so
  // they are split back into hypothesis/reason on the first colon and fall
  // back to a single line when a bullet has no colon in it.
  function rejectedBlock(alert, parts) {
    var structured = [];
    var raw = alert.rejected_hypotheses || [];
    for (var j = 0; j < raw.length; j++) {
      if (raw[j] && raw[j][0]) structured.push([raw[j][0], raw[j][1] || '']);
    }

    var heading = t('rHead');
    var pairs = [];
    if (state.lang === 'bn') {
      // The server publishes the Bengali rejections only as pre-rendered prose,
      // so recover the bullets — but only when they pair up one-for-one with the
      // structured list. Naming *every* rejected hypothesis matters more than
      // localising it, so a mismatch falls back to the structured wording.
      var parsed = parseRejectedText(parts.rejected_text);
      if (parsed.heading) heading = parsed.heading;
      if (parsed.pairs.length === structured.length) pairs = parsed.pairs;
    }
    if (!pairs.length) pairs = structured;

    if (!pairs.length) return '';

    var html = '<div class="rejected"><h4>' + esc(heading) + '</h4><dl>';
    for (var k = 0; k < pairs.length; k++) {
      html += '<dt>' + esc(pairs[k][0]) + '</dt>'
        + '<dd>' + esc(pairs[k][1] || t('unknown')) + '</dd>';
    }
    return html + '</dl></div>';
  }

  // The Bengali rejection block arrives as "heading:\n  • hyp: reason\n  • …".
  // Split on the *first* colon only: a reason may contain one itself.
  function parseRejectedText(text) {
    var out = { heading: '', pairs: [] };
    var lines = String(text || '').split('\n');
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].replace(/^\s*•\s*/, '').trim();
      if (!line) continue;
      if (line.charAt(line.length - 1) === ':') {
        out.heading = line.replace(/:+$/, '');
        continue;
      }
      var cut = line.indexOf(':');
      if (cut > 0) out.pairs.push([line.slice(0, cut).trim(), line.slice(cut + 1).trim()]);
      else out.pairs.push([line, '']);
    }
    return out;
  }

  function actionsBlock(alert) {
    var actors = '<option value="central">' + esc(t('trackAll')) + '</option>';
    var providers = providerList();
    for (var i = 0; i < providers.length; i++) {
      actors += '<option value="' + esc(providers[i].id) + '">'
        + esc(providerLabel(providers[i])) + '</option>';
    }
    var disabled = state.busy ? ' disabled' : '';
    return '<div class="d-actions">'
      + '<input class="note-input" id="a-note" type="text" aria-label="'
      + esc(t('noteLabel')) + '" placeholder="' + esc(t('notePh')) + '"' + disabled + '>'
      + '<input class="note-input" id="a-actor" type="text" aria-label="'
      + esc(t('actorLabel')) + '" placeholder="' + esc(t('actorPh'))
      + '" value="' + esc(state.actor || '') + '"' + disabled + '>'
      + '<div class="field"><label for="a-track">' + esc(t('trackLabel'))
      + '</label><select id="a-track"' + disabled + '>' + actors + '</select></div>'
      + actButton('acknowledge', t('actionAck'), ICON.check, 'primary', disabled)
      + actButton('escalate', t('actionEscalate'), ICON.up, 'danger', disabled)
      + actButton('resolve', t('actionResolve'), ICON.done, '', disabled)
      + actButton('note', t('actionNote'), ICON.note, '', disabled)
      + '</div>'
      + '<div id="boundary"></div>';
  }

  function actButton(action, label, icon, variant, disabled) {
    return '<button class="btn btn-act' + (variant ? ' ' + variant : '')
      + '" type="button" data-act="' + action + '"' + disabled + '>'
      + svgIcon(icon) + '<span>' + esc(label) + '</span></button>';
  }

  function historyBlock(history, alert) {
    var html = '<div class="parts"><div class="part"><h4>'
      + esc(t('caseHistory')) + '</h4>';
    if (!history || !history.length) {
      html += '<p class="hint">' + esc(t('noHistory')) + '</p>';
    } else {
      for (var i = 0; i < history.length; i++) {
        html += evRow(history[i], alert.id);
      }
    }
    return html + '</div></div>';
  }

  function evRow(event, alertId) {
    var what = String(event.action || '') + ' · ' + String(alertId || '');
    if (event.note) what += ' — ' + event.note;
    return '<div class="ev">'
      + '<time datetime="' + esc(isoTime(event.ts)) + '">' + fTime(event.ts) + '</time>'
      + '<span class="who" lang="en">' + esc(event.actor || '') + '</span>'
      + '<span class="what">' + esc(what) + '</span>'
      + '</div>';
  }

  /* ---------------------------------------------------------- runway view */

  function riskRank(outlet) {
    if (!finite(outlet.worst_hours)) return 1e9;
    return outlet.worst_hours;
  }

  function isAtRisk(outlet) {
    return finite(outlet.worst_hours) && outlet.worst_hours <= HORIZON_HOURS;
  }

  function axisPct(hours) {
    if (!finite(hours)) return null;
    var p = (hours / HORIZON_HOURS) * 100;
    if (p < 0) p = 0;
    if (p > 100) p = 100;
    return Math.round(p * 100) / 100;
  }

  function runwayStrip(proj) {
    var tick = Math.round((100 / HORIZON_HOURS) * 100) / 100;
    if (proj.exhausted) {
      return '<div class="runway depleted"><span class="runway-tag">'
        + esc(t('depleted')) + '</span></div>';
    }
    if (proj.suppressed) {
      return '<div class="runway suppressed"><span class="runway-tag">'
        + esc(t('suppressedTag')) + '</span></div>';
    }
    if (proj.point === null) {
      // No point estimate. If the server still published an interval, draw that
      // rather than claiming nothing was projected.
      var lo = axisPct(proj.low);
      var hi = axisPct(proj.high);
      if (lo === null || hi === null) {
        return '<div class="runway none"><span class="runway-tag">'
          + esc(t('noDepletion')) + '</span></div>';
      }
      if (lo > hi) { var sw = lo; lo = hi; hi = sw; }
      return '<div class="runway" style="--tick:' + tick + '" title="'
        + esc(intervalText(proj)) + '">' + bandSpan(lo, hi) + '</div>';
    }
    var point = axisPct(proj.point);
    var low = axisPct(proj.low);
    var high = axisPct(proj.high);
    if (low === null || high === null) { low = point; high = point; }
    if (low > high) { var swap = low; low = high; high = swap; }
    // A projection that lands past the horizon is still a projection, so the
    // pin stays clamped at the right edge and the strip says so in words. A
    // lower bound that reaches back inside the horizon still draws its width.
    // No width is possible out there, so the tag carries the interval itself:
    // a hover-only title would hide it from touch and keyboard users.
    var late = proj.point > HORIZON_HOURS;
    return '<div class="runway" style="--tick:' + tick + '" title="'
      + esc(intervalText(proj)) + '">' + bandSpan(low, high)
      + '<span class="pin" style="left:' + point + '%"></span>'
      + (late ? '<span class="runway-tag">' + esc(t('beyondHorizon') + ' · '
          + intervalText(proj)) + '</span>' : '')
      + '</div>';
  }

  // Width is a percentage of an axis, not a figure: the browser never computes
  // a balance or a rate, only where on a 0–6 h scale a published hour sits.
  function bandSpan(low, high) {
    if (high - low <= 0.15) return '';
    return '<span class="band" style="left:' + low + '%;width:'
      + (Math.round((high - low) * 100) / 100) + '%"></span>';
  }

  function intervalText(proj) {
    var unit = t('unitHoursShort');
    if (finite(proj.low) && finite(proj.high)) {
      return fHours(proj.low) + '–' + fHours(proj.high) + ' ' + unit;
    }
    return fHours(proj.point) + ' ' + unit;
  }

  function hoursCell(proj) {
    if (proj.exhausted) {
      return '<span class="r-hours critical" title="' + esc(t('depleted')) + '">'
        + fHours(0) + ' ' + esc(t('unitHoursShort')) + '</span>';
    }
    if (proj.suppressed) {
      return '<span class="r-hours high">' + esc(t('verifyFeed')) + '</span>';
    }
    if (proj.point === null) {
      return '<span class="r-hours none">' + esc(t('noProjection')) + '</span>';
    }
    var cls = 'r-hours';
    if (finite(proj.point) && proj.point <= HORIZON_HOURS) {
      cls += proj.point <= HORIZON_HOURS * 0.25 ? ' critical' : ' high';
    }
    return '<span class="' + cls + '" title="' + esc(intervalText(proj)) + '">'
      + fHours(proj.point) + ' ' + esc(t('unitHoursShort')) + '</span>';
  }

  // Feed provenance, per provider, for the providers whose feed is not fresh.
  // A healthy outlet renders no line at all, which is what makes a stale or
  // conflicting feed read as different rather than merely present.
  function feedAge(pos) {
    return finite(pos.feed_age_minutes)
      ? ' ' + fInt(pos.feed_age_minutes) + ' ' + t('feedAge') : '';
  }

  function feedLine(outlet) {
    var positions = outlet.positions || [];
    var bad = [];
    for (var i = 0; i < positions.length; i++) {
      var pos = positions[i];
      if (pos.feed_status === 'fresh') continue;
      bad.push(tag(FEED_TAG[pos.feed_status] || 'dq',
        providerName(pos.provider_id, positions) + ': '
        + feedLabel(pos.feed_status) + feedAge(pos)));
    }
    return bad.length ? '<div class="horizon-note">' + bad.join(' ') + '</div>' : '';
  }

  // The runway stays a direct child of .row: at the 640px breakpoint the CSS
  // moves it with grid-area, which only works if it is a grid item itself.
  function rowHtml(kindClass, label, proj, pos) {
    var lowConf = pos && pos.low_confidence
      ? ' <span class="lowconf">' + esc(t('lowConf')) + '</span>' : '';
    var feed = pos ? feedLabel(pos.feed_status) + feedAge(pos) : '';
    return '<div class="row ' + kindClass + '">'
      + '<span class="r-label" title="' + esc(feed) + '">' + esc(label)
      + lowConf + '</span>'
      + '<span class="r-bal">' + fBdt(proj.balance) + '</span>'
      + hoursCell(proj)
      + runwayStrip(proj)
      + '</div>';
  }

  function cashProj(outlet) {
    return {
      balance: outlet.cash,
      point: finite(outlet.cash_hours) ? outlet.cash_hours : null,
      low: null,
      high: null,
      exhausted: !!outlet.cash_exhausted,
      suppressed: false
    };
  }

  function posProj(pos) {
    return {
      balance: pos.balance,
      point: finite(pos.hours_to_empty) ? pos.hours_to_empty : null,
      low: finite(pos.low_hours) ? pos.low_hours : null,
      high: finite(pos.high_hours) ? pos.high_hours : null,
      exhausted: !!pos.exhausted,
      suppressed: !!pos.suppressed
    };
  }

  function renderOutlets() {
    var host = $('#outlets');
    if (!host || !state.snapshot) return;
    var outlets = (state.snapshot.outlets || []).slice();
    if (!outlets.length) {
      host.innerHTML = emptyBlock(t('oNoTxnTitle'), t('oNoTxnBody'));
      return;
    }
    // Riskiest first: the signature view should open on the story, not on
    // whichever outlet happens to be first in the world.
    outlets.sort(function (a, b) {
      var d = riskRank(a) - riskRank(b);
      return d !== 0 ? d : (a.id < b.id ? -1 : 1);
    });

    var focusOutlet = state.snapshot.focus && state.snapshot.focus.outlet_id;
    var selected = null;
    for (var i = 0; i < state.alerts.length; i++) {
      if (state.alerts[i].id === state.selectedId) selected = state.alerts[i];
    }

    var html = '';
    for (var j = 0; j < outlets.length; j++) {
      var o = outlets[j];
      var risk = isAtRisk(o);
      var isFocus = o.id === focusOutlet || (selected && selected.outlet_id === o.id);
      html += '<div class="outlet' + (risk ? ' is-risk' : '')
        + (isFocus ? ' is-focused' : '') + '">';
      html += '<div class="o-head">'
        + '<span class="o-name" lang="en">' + esc(o.name) + '</span>'
        + '<span class="o-place" lang="en">' + esc(o.thana) + ', ' + esc(o.area)
        + ' · ' + esc(o.id) + '</span>'
        + '<span class="o-total">' + fBdt(o.total_value) + ' '
        + esc(t('oTotal')) + '</span>'
        + '</div>';

      if (!o.txn_count) {
        html += emptyBlock(t('oNoTxnTitle'), t('oNoTxnBody'));
      } else if (!o.positions || !o.positions.length) {
        html += '<p class="hint">' + esc(t('oNoPositions')) + '</p>';
      } else {
        html += rowHtml('r-cash', t('cashRow'), cashProj(o), null);
        for (var k = 0; k < o.positions.length; k++) {
          var pos = o.positions[k];
          html += rowHtml('r-float', providerName(pos.provider_id, o.positions),
                          posProj(pos), pos);
        }
        html += feedLine(o);
      }

      var notes = [];
      notes.push(t('oAxis'));
      notes.push(t('oTxns') + ': ' + fInt(o.txn_count));
      notes.push(t('oReliability') + ': ' + fRatio(o.reliability));
      if (o.reliability_notes && o.reliability_notes.length) {
        for (var n = 0; n < o.reliability_notes.length; n++) {
          notes.push(o.reliability_notes[n]);
        }
      }
      html += '<div class="horizon-note">' + esc(notes.join(' · ')) + '</div>';
      html += '</div>';
    }
    host.innerHTML = html;
  }

  /* ------------------------------------------------------------- map view */

  function projector(items) {
    var lats = [], lons = [];
    for (var i = 0; i < items.length; i++) {
      if (finite(items[i].lat) && finite(items[i].lon)) {
        lats.push(items[i].lat); lons.push(items[i].lon);
      }
    }
    if (!lats.length) return null;
    var minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
    var minLon = Math.min.apply(null, lons), maxLon = Math.max.apply(null, lons);
    var spanLat = maxLat - minLat, spanLon = maxLon - minLon;
    if (spanLat < 0.01) { minLat -= 0.005; maxLat += 0.005; spanLat = maxLat - minLat; }
    if (spanLon < 0.01) { minLon -= 0.005; maxLon += 0.005; spanLon = maxLon - minLon; }
    return function (item) {
      // Longitude spans more degrees than latitude at this scale, so the two
      // axes are fitted rather than shared; this is drawing geometry only.
      var x = 40 + ((item.lon - minLon) / spanLon) * 560;
      var y = 30 + ((maxLat - item.lat) / spanLat) * 330;
      return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
    };
  }

  // Greedy label placement: a label is dropped rather than overprinted, so a
  // dense cluster degrades into fewer legible labels instead of a smear.
  function labelPlacer() {
    var placed = [];
    return function (x, y, text) {
      var width = String(text).length * 5.9 + 6;
      var box = [x - 2, y - 9, x + width, y + 4];
      for (var i = 0; i < placed.length; i++) {
        var p = placed[i];
        if (box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1]) return false;
      }
      placed.push(box);
      return true;
    };
  }

  function renderMap() {
    var host = $('#map');
    var count = $('#map-count');
    if (!host || !state.snapshot) return;
    var areas = (state.snapshot.hotspots && state.snapshot.hotspots.areas) || [];
    var top = (state.snapshot.hotspots && state.snapshot.hotspots.summary) || {};
    var outlets = state.snapshot.outlets || [];

    if (count) {
      count.textContent = fInt(top.areas) + ' ' + t('mapAreas') + ' · '
        + fInt(top.outlets) + ' ' + t('kOutlets') + ' · '
        + fInt(top.at_risk) + ' ' + t('mapAtRisk')
        + (top.worst_area ? ' · ' + t('mapWorst') + ': ' + top.worst_area : '');
    }

    var project = projector(outlets);
    if (!project || !outlets.length) {
      host.innerHTML = emptyBlock(t('mapEmptyTitle'), t('mapEmptyBody'));
      return;
    }

    var svg = '<svg viewBox="0 0 640 400" role="img" aria-label="'
      + esc(t('mapAlt')) + ' — ' + esc(fInt(top.outlets) + ' ' + t('kOutlets')
      + ', ' + fInt(top.at_risk) + ' ' + t('mapAtRisk')) + '">';
    svg += '<title>' + esc(t('mapAlt')) + '</title>';

    // Area halos first, so dots and labels stay on top.
    var perArea = {};
    for (var i = 0; i < areas.length; i++) {
      var area = areas[i];
      perArea[area.area] = area;
      var members = [];
      for (var j = 0; j < outlets.length; j++) {
        if (outlets[j].area === area.area) members.push(outlets[j]);
      }
      if (!members.length) continue;
      var cx = 0, cy = 0;
      for (var k = 0; k < members.length; k++) {
        var pt = project(members[k]);
        cx += pt[0]; cy += pt[1];
      }
      var ax = cx / members.length, ay = cy / members.length;
      var radius = area.at_risk_count > 0 ? 34 + area.at_risk_count * 6 : 20;
      svg += '<circle cx="' + ax + '" cy="' + ay + '" r="' + radius
        + '" fill="' + (area.at_risk_count > 0 ? 'var(--alert)' : 'var(--float)')
        + '" fill-opacity="' + (area.at_risk_count > 0 ? '0.12' : '0.05') + '"/>';
    }

    // Outlet dots: colour carries the same meaning as the runway rows.
    var place = labelPlacer();
    var labels = '';
    var areaCentroids = {};
    for (var m = 0; m < outlets.length; m++) {
      var o = outlets[m];
      var p = project(o);
      var status = isAtRisk(o) ? (riskRank(o) <= HORIZON_HOURS * 0.25 ? 'alert' : 'warn')
        : 'ok';
      var colour = status === 'alert' ? 'var(--alert)'
        : status === 'warn' ? 'var(--warn)' : 'var(--ok)';
      var tip = o.name + ' · ' + o.id + ' — '
        + (isAtRisk(o) ? t('kAtRisk') : t('verdictNone'));
      svg += '<circle class="map-dot" cx="' + p[0] + '" cy="' + p[1] + '" r="'
        + (status === 'alert' ? 9 : status === 'warn' ? 7.5 : 6)
        + '" style="fill:' + colour + ';stroke:var(--ink);stroke-width:1.5"'
        + ' data-outlet="' + esc(o.id) + '"><title>' + esc(tip) + '</title></circle>';
      if (!areaCentroids[o.area]) areaCentroids[o.area] = p;
    }

    var areasList = Object.keys(areaCentroids);
    for (var a = 0; a < areasList.length; a++) {
      var name = areasList[a];
      var spot = areaCentroids[name];
      var info = perArea[name];
      var text = name + (info && info.at_risk_count > 0
        ? ' (' + fInt(info.at_risk_count) + ')' : '');
      if (place(spot[0], spot[1] + 22, text)) {
        labels += '<text class="map-label" x="' + spot[0] + '" y="' + (spot[1] + 22)
          + '">' + esc(text) + '</text>';
      }
    }

    svg += labels + '</svg>';
    svg += '<p class="horizon-note">' + esc(top.note || '') + '</p>';
    host.innerHTML = svg;
  }

  /* ----------------------------------------------------------- areas view */

  function renderAreas() {
    var host = $('#areas');
    var support = $('#support');
    if (!host || !state.snapshot) return;
    var areas = (state.snapshot.hotspots && state.snapshot.hotspots.areas) || [];

    if (!areas.length) {
      host.innerHTML = emptyBlock(t('areasEmptyTitle'), t('areasEmptyBody'));
    } else {
      var maxOutlets = 0;
      for (var i = 0; i < areas.length; i++) {
        if (areas[i].outlet_count > maxOutlets) maxOutlets = areas[i].outlet_count;
      }
      var html = '<table><thead><tr>'
        + '<th>' + esc(t('thArea')) + '</th>'
        + '<th class="num">' + esc(t('thOutlets')) + '</th>'
        + '<th class="num">' + esc(t('thAtRisk')) + '</th>'
        + '<th class="num">' + esc(t('thCash')) + '</th>'
        + '<th class="num">' + esc(t('thEmoney')) + '</th>'
        + '<th class="bar-cell">' + esc(t('thPressure')) + '</th>'
        + '</tr></thead><tbody>';
      for (var j = 0; j < areas.length; j++) {
        var area = areas[j];
        // A ratio of two counts — outlets at risk over outlets in the area.
        // No money is divided here.
        var share = maxOutlets > 0 ? (area.at_risk_count / maxOutlets) * 100 : 0;
        var calm = area.at_risk_count === 0 ? ' calm' : '';
        html += '<tr>'
          + '<td lang="en">' + esc(area.area) + '</td>'
          + '<td class="num">' + fInt(area.outlet_count) + '</td>'
          + '<td class="num">' + fInt(area.at_risk_count) + '</td>'
          + '<td class="num">' + fBdt(area.total_cash) + '</td>'
          + '<td class="num">' + fBdt(area.total_emoney) + '</td>'
          + '<td class="bar-cell"><div class="hbar' + calm + '"><i style="width:'
          + (Math.round(share * 10) / 10) + '%"></i></div></td>'
          + '</tr>';
      }
      host.innerHTML = html + '</tbody></table>';
    }
    renderSupport();
  }

  function renderSupport() {
    var host = $('#support');
    if (!host || !state.snapshot) return;
    var support = state.snapshot.support || [];
    if (!support.length) {
      host.innerHTML = '<h3>' + esc(t('supportHead')) + '</h3><div class="empty">'
        + esc(t('supportEmpty')) + '</div>';
      return;
    }
    var html = '<h3>' + esc(t('supportHead')) + '</h3>';
    for (var i = 0; i < support.length; i++) {
      var s = support[i];
      var headroom = finite(s.hours_of_headroom)
        ? fHours(s.hours_of_headroom) + ' ' + t('unitHoursShort')
        : t('noDepletion');
      html += '<div class="support-card">'
        + '<div class="route">'
        + '<span>' + esc(s.outlet_id_source || '') + '</span>'
        + '<span aria-hidden="true">→</span>'
        + '<span>' + esc(s.outlet_id) + '</span>'
        + '<span>· ' + esc(providerName(s.provider_id,
            positionsOf(s.outlet_id_source))) + '</span>'
        + '<span>· ' + esc(t('supportHeadroom')) + ': ' + esc(headroom) + '</span>'
        + '<span>· ' + esc(t('supportDistance')) + ': ' + fKm(s.distance_km)
        + ' ' + esc(t('supportKm')) + '</span>'
        + '<span>· ' + esc(s.same_area ? t('supportSameArea') : t('supportOtherArea'))
        + '</span>'
        + '</div>'
        + '<p>' + esc(s.note || '') + '</p>'
        + '</div>';
    }
    host.innerHTML = html;
  }

  /* --------------------------------------------------------- network view */

  function renderNetwork() {
    var host = $('#network');
    if (!host || !state.snapshot) return;
    var net = state.snapshot.network || {};
    var nodes = net.nodes || [];
    var edges = net.edges || [];
    var summary = net.summary || {};
    var outlets = state.snapshot.outlets || [];

    if (!nodes.length || !edges.length) {
      host.innerHTML = emptyBlock(t('netEmptyTitle'), t('netEmptyBody'));
      return;
    }

    var byId = {};
    var networkIds = [];
    for (var i = 0; i < nodes.length; i++) {
      var ids = nodes[i].outlet_ids || [];
      for (var j = 0; j < ids.length; j++) {
        if (networkIds.indexOf(ids[j]) === -1) networkIds.push(ids[j]);
      }
      if (nodes[i].is_concentrated) {
        for (var k = 0; k < ids.length; k++) byId[ids[k]] = true;
      }
    }
    var present = [];
    for (var m = 0; m < outlets.length; m++) {
      if (networkIds.indexOf(outlets[m].id) !== -1) present.push(outlets[m]);
    }
    var project = projector(present.length ? present : outlets);
    if (!project) {
      host.innerHTML = emptyBlock(t('netEmptyTitle'), t('netEmptyBody'));
      return;
    }

    var svg = '<svg viewBox="0 0 640 400" role="img" aria-label="'
      + esc(t('netAlt')) + ' — ' + esc(fInt(summary.shared_accounts) + ' '
      + t('netSharedAccounts') + ', ' + fInt(summary.links) + ' ' + t('netLinks'))
      + '">';
    svg += '<title>' + esc(t('netAlt')) + '</title>';

    var maxShared = 0;
    for (var e = 0; e < edges.length; e++) {
      if (edges[e].shared_txns > maxShared) maxShared = edges[e].shared_txns;
    }
    var points = {};
    for (var n = 0; n < present.length; n++) {
      points[present[n].id] = project(present[n]);
    }
    for (var f = 0; f < edges.length; f++) {
      var edge = edges[f];
      var from = points[edge.source], to = points[edge.target];
      if (!from || !to) continue;
      var strong = byId[edge.source] || byId[edge.target];
      var width = maxShared > 0
        ? 1 + (edge.shared_txns / maxShared) * 2.6 : 1.2;
      svg += '<line class="net-edge" x1="' + from[0] + '" y1="' + from[1]
        + '" x2="' + to[0] + '" y2="' + to[1] + '" stroke-width="'
        + (Math.round(width * 10) / 10) + '"'
        + (strong ? ' style="stroke:var(--alert);stroke-opacity:.45"' : '')
        + '><title>' + esc(edge.source + ' ↔ ' + edge.target + ' — '
        + fInt(edge.shared_txns) + ' ' + t('oTxns')) + '</title></line>';
    }

    var place = labelPlacer();
    for (var q = 0; q < present.length; q++) {
      var o = present[q];
      var pt = points[o.id];
      var concentrated = !!byId[o.id];
      svg += '<circle class="net-node' + (concentrated ? ' concentrated' : '')
        + '" cx="' + pt[0] + '" cy="' + pt[1] + '" r="'
        + (concentrated ? 8 : 6) + '"><title>' + esc(o.name + ' · ' + o.id
        + (concentrated ? ' — ' + t('netConcentrated') : '')) + '</title></circle>';
      if (place(pt[0] + 10, pt[1] + 3, o.id)) {
        svg += '<text class="net-name" x="' + (pt[0] + 10) + '" y="' + (pt[1] + 3)
          + '">' + esc(o.id) + '</text>';
      }
    }
    svg += '</svg>';

    var legend = fInt(summary.shared_accounts) + ' ' + t('netSharedAccounts')
      + ' · ' + fInt(summary.concentrated_accounts) + ' ' + t('netConcentrated')
      + ' · ' + fInt(summary.links) + ' ' + t('netLinks')
      + ' · ' + t('netLabels');
    if (net.cross_provider && net.cross_provider.length) {
      legend += '<br>' + fInt(net.cross_provider.length) + ' ' + t('netCross');
    }
    if (summary.note) legend += '<br>' + esc(summary.note);

    host.innerHTML = '<div class="net-wrap">' + svg + '</div>'
      + '<p class="net-legend">' + legend + '</p>';
  }

  /* ---------------------------------------------------------- what-if view */

  function metricRow(label, value, tone) {
    return '<div class="m-row' + (tone ? ' ' + tone : '') + '"><span>'
      + esc(label) + '</span><b>' + esc(value) + '</b></div>';
  }

  function renderWhatIf() {
    var host = $('#whatif');
    if (!host || !state.snapshot) return;
    var snap = state.snapshot;
    var existing = host.querySelector('#wi-demand');
    var demand = finite(snap.demand_multiplier) ? snap.demand_multiplier : 1.0;
    state.demand = demand;

    if (existing) {
      // The controls already exist: update in place so a drag is never stolen
      // by a re-render landing mid-gesture.
      if (document.activeElement !== existing) {
        existing.value = String(demand);
      }
      var output = host.querySelector('#wi-angle output');
      if (output) output.textContent = fRatio(demand) + '×';
      var applied = host.querySelector('#wi-applied');
      if (applied) applied.textContent = appliedText(snap);
      var toggle = host.querySelector('#wi-event');
      if (toggle) {
        var on = Math.abs(demand - EVENT_DEMAND) < 0.001;
        toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
        toggle.className = on ? 'btn btn-act primary' : 'btn btn-act';
      }
      return;
    }

    host.innerHTML = '<div class="slider-row" id="wi-angle">'
      + '<label for="wi-demand"><span>' + esc(t('wiDemand')) + '</span>'
      + '<output>' + fRatio(demand) + '×</output></label>'
      + '<input id="wi-demand" type="range" min="' + DEMAND_MIN + '" max="'
      + DEMAND_MAX + '" step="0.1" value="' + demand + '">'
      + '</div>'
      + '<div class="slider-row">'
      + '<button class="btn btn-act' + (Math.abs(demand - EVENT_DEMAND) < 0.001
          ? ' primary' : '') + '" type="button" id="wi-event" aria-pressed="'
      + (Math.abs(demand - EVENT_DEMAND) < 0.001 ? 'true' : 'false') + '">'
      + svgIcon(ICON.run) + '<span>' + esc(t('wiEvent')) + '</span></button> '
      + '<button class="btn btn-act" type="button" id="wi-run">'
      + svgIcon(ICON.run) + '<span>' + esc(t('wiRun')) + '</span></button>'
      + '</div>'
      + '<p class="hint" id="wi-applied">' + esc(appliedText(snap)) + '</p>'
      + '<p class="hint">' + esc(t('wiHint')) + '</p>';
  }

  function appliedText(snap) {
    return t('wiApplied') + ': ' + fRatio(snap.demand_multiplier) + '× · '
      + fInt(snap.summary ? snap.summary.outlets : snap.outlets.length) + ' '
      + t('kOutlets') + ' · seed ' + esc(String(snap.seed));
  }

  function renderMetrics() {
    var host = $('#metrics');
    if (!host || !state.snapshot) return;
    var m = state.snapshot.metrics || {};
    if (m.episodes == null) {
      host.innerHTML = emptyBlock(t('metricsEmpty'), '');
      return;
    }
    var html = '';
    html += metricRow(t('mEpisodes'), fInt(m.episodes));
    html += metricRow(t('mExpected'), fInt(m.expected_findings));
    html += metricRow(t('mDetected'), fInt(m.detected_findings));
    html += metricRow(t('mTP'), fInt(m.true_positives),
                      m.true_positives > 0 ? 'good' : '');
    html += metricRow(t('mFP'), fInt(m.false_positives),
                      m.false_positives > 0 ? 'bad' : 'good');
    html += metricRow(t('mFN'), fInt(m.false_negatives),
                      m.false_negatives > 0 ? 'bad' : 'good');
    // Precision and recall are shown exactly as measured, as ratios, so the
    // browser never converts a measured figure into a different one.
    html += metricRow(t('mPrecision'), fRatio(m.precision));
    html += metricRow(t('mRecall'), fRatio(m.recall));
    html += metricRow(t('mFPR'), fRatio(m.false_positive_rate));
    html += metricRow(t('mSpike'), fInt(m.demand_spike_episodes));
    html += metricRow(t('mNeedsReview'), fInt(m.needs_review_alerts));
    html += '<div class="m-row"><span class="hint">' + esc(m.note || '') + '</span></div>';
    host.innerHTML = html;
  }

  /* ------------------------------------------------------------ audit view */

  function renderAudit() {
    var host = $('#audit');
    if (!host) return;
    if (state.casesError) {
      host.innerHTML = emptyBlock(t('loadFailed'), state.casesError);
      return;
    }
    var cases = state.cases || [];
    if (!cases.length) {
      host.innerHTML = emptyBlock(t('auditEmptyTitle'), t('auditEmptyBody'));
      return;
    }
    var shown = cases.slice(0, MAX_AUDIT_ROWS);
    var html = '';
    for (var i = 0; i < shown.length; i++) {
      html += evRow(shown[i], shown[i].alert_id);
    }
    if (cases.length > shown.length) {
      html += '<p class="horizon-note">' + esc(t('auditTruncated')
        .replace('{shown}', fInt(shown.length))
        .replace('{total}', fInt(cases.length))) + '</p>';
    }
    host.innerHTML = html;
  }

  function renderFatal(error) {
    state.fatal = error;
    var message = (error && error.detail) || (error && error.message)
      || t('loadFailed');
    state.alerts = [];
    state.snapshot = null;
    var panels = ['#focus', '#kpis', '#queue', '#detail', '#outlets', '#map',
                  '#areas', '#support', '#network', '#whatif', '#metrics'];
    for (var i = 0; i < panels.length; i++) {
      var node = $(panels[i]);
      if (node) node.innerHTML = emptyBlock(t('loadFailed'), message);
    }
    var audit = $('#audit');
    if (audit) audit.innerHTML = emptyBlock(t('loadFailed'), message);
    toast(t('loadFailed') + ' — ' + message, true);
  }

  function renderAll() {
    if (!state.snapshot) return;
    renderFocus();
    renderKpis();
    renderQueue();
    renderDetail();
    renderOutlets();
    renderMap();
    renderAreas();
    renderNetwork();
    renderWhatIf();
    renderMetrics();
    renderAudit();
  }

  /* ------------------------------------------------------------- behaviour */

  function setLang(lang) {
    if (lang !== 'bn' && lang !== 'en') return;
    state.lang = lang;
    state.detailKey = '';
    applyI18n();
    if (state.snapshot) renderAll();
    else renderFatal(state.fatal || new Error(t('loadFailed')));
    // The what-if controls are rebuilt from scratch on a language change so
    // their labels follow; the slider value is re-read from the snapshot.
    var whatif = $('#whatif');
    if (whatif) whatif.innerHTML = '';
    if (state.snapshot) renderWhatIf();
  }

  function loadAlertHistory(id, token) {
    return api('/api/alerts/' + encodeURIComponent(id)).then(function (detail) {
      if (token !== state.detailToken) return;
      // Guard rather than trust: a response that names a different alert must
      // never be written into this slot, or the queue would lose an entry.
      if (detail && detail.id !== id) return;
      var history = detail.history || [];
      // The detail endpoint attaches the case trail to the alert payload; it is
      // kept beside the alert rather than inside it so the rendered alert stays
      // exactly the shape the rest of the snapshot uses.
      delete detail.history;
      for (var i = 0; i < state.alerts.length; i++) {
        if (state.alerts[i].id === id) { state.alerts[i] = detail; break; }
      }
      state.history[id] = history;
      state.detailKey = '';
      renderDetail();
    }).catch(function () {
      // A missing case trail must not blank the alert itself.
      if (token !== state.detailToken) return;
      state.history[id] = state.history[id] || [];
    });
  }

  function refresh() {
    return Promise.all([
      api('/api/state'),
      api('/api/cases').then(function (cases) { return { cases: cases }; },
                            function (err) { return { error: err }; })
    ]).then(function (results) {
      var snap = results[0];
      var cases = results[1];
      state.snapshot = snap;
      state.alerts = snap.alerts || [];
      state.fatal = null;
      if (cases.error) {
        state.casesError = cases.error.detail || cases.error.message;
      } else {
        state.cases = cases.cases || [];
        state.casesError = null;
      }
      if (state.selectedId && !findAlert(state.selectedId)) state.selectedId = null;
      renderAll();
      // The server names the outlet and the case each named scenario is about
      // (see Engine._resolve_focus), so the dashboard opens on that story.
      var focus = snap.focus || {};
      if (focus.alert_id) selectAlert(focus.alert_id);
      else if (!state.selectedId && state.alerts.length) {
        selectAlert(state.alerts[0].id);
      }
      return snap;
    }).catch(function (error) {
      renderFatal(error);
      return null;
    });
  }

  function findAlert(id) {
    for (var i = 0; i < state.alerts.length; i++) {
      if (state.alerts[i].id === id) return state.alerts[i];
    }
    return null;
  }

  function selectAlert(id) {
    if (!id) return;
    var changed = state.selectedId !== id;
    state.selectedId = id;
    if (changed) state.detailKey = '';
    renderQueue();
    renderDetail();
    renderOutlets();
    // A slow response for a previous selection must not overwrite the panel the
    // operator is now looking at, so every load carries a token.
    return loadAlertHistory(id, ++state.detailToken);
  }

  function focusOutlet(id) {
    var outlet = outletById(id);
    if (!outlet) return;
    // Prefer the most severe open case at that outlet, which the server already
    // ordered for the queue; otherwise just look at the outlet's runways.
    for (var i = 0; i < state.alerts.length; i++) {
      if (state.alerts[i].outlet_id === id) { selectAlert(state.alerts[i].id); return; }
    }
    state.selectedId = null;
    state.detailKey = '';
    renderQueue();
    renderDetail();
    renderOutlets();
    var node = $('#outlets');
    if (node) fadeIn(node, 200);
  }

  function simulate(payload, onDone) {
    if (state.busy) return Promise.resolve(null);
    state.busy = true;
    setControlsDisabled(true);
    return postJson('/api/simulate', payload).then(function (snap) {
      state.busy = false;
      setControlsDisabled(false);
      state.snapshot = snap;
      state.alerts = snap.alerts || [];
      if (state.selectedId && !findAlert(state.selectedId)) state.selectedId = null;
      state.detailKey = '';
      renderAll();
      var outlets = $('#outlets');
      if (outlets) fadeIn(outlets, 240);
      if (!state.selectedId && state.alerts.length) selectAlert(state.alerts[0].id);
      if (typeof onDone === 'function') onDone(snap);
      return snap;
    }).catch(function (error) {
      state.busy = false;
      setControlsDisabled(false);
      toast((error && error.detail) || t('actionFailed'), true);
      return null;
    });
  }

  function setControlsDisabled(disabled) {
    var ids = ['#scenario', '#wi-demand', '#wi-run', '#wi-event'];
    for (var i = 0; i < ids.length; i++) {
      var node = $(ids[i]);
      if (node) node.disabled = !!disabled;
    }
  }

  function doAction(action) {
    if (state.busy || !state.selectedId) return;
    var noteNode = $('#a-note');
    var actorNode = $('#a-actor');
    var trackNode = $('#a-track');
    var note = noteNode ? noteNode.value.trim() : '';
    var actor = actorNode ? actorNode.value.trim() : '';
    var track = trackNode ? trackNode.value : 'central';
    if (actor) state.actor = actor;
    if (action === 'note' && !note) {
      toast(t('noteRequired'), true);
      if (noteNode) noteNode.focus();
      return;
    }
    var id = state.selectedId;
    // Remember which control had focus: the panel is rebuilt on the response
    // and a rebuilt subtree would otherwise drop focus to the document body.
    var active = document.activeElement;
    var restoreAct = active && active.getAttribute
      ? active.getAttribute('data-act') : null;

    state.busy = true;
    setControlsDisabled(true);
    return postJson('/api/alerts/' + encodeURIComponent(id) + '/action', {
      action: action, actor: actor || 'dashboard_user', note: note,
      actor_provider: track
    }).then(function (updated) {
      state.busy = false;
      setControlsDisabled(false);
      applyUpdatedAlert(id, updated, restoreAct);
      toast(t('actionRecorded') + ' — ' + action);
      return refreshCases(id);
    }).catch(function (error) {
      state.busy = false;
      setControlsDisabled(false);
      if (error && error.status === 403) {
        showBoundary(error);
      } else {
        toast((error && error.detail) || t('actionFailed'), true);
        if (error && error.status === 404) refresh();
      }
      return null;
    });
  }

  function applyUpdatedAlert(id, updated, restoreAct) {
    var history = state.history[id] || [];
    var replaced = false;
    for (var i = 0; i < state.alerts.length; i++) {
      if (state.alerts[i].id === id) {
        state.alerts[i] = updated;
        replaced = true;
        break;
      }
    }
    if (!replaced) state.alerts.push(updated);
    state.history[id] = history;
    // The POST response is the authoritative post-action state of this case
    // (the snapshot's copy of an alert is not rewritten in place server-side),
    // so the local list is updated from it rather than re-fetched.
    state.detailKey = '';
    renderQueue();
    renderDetail();
    renderOutlets();
    if (restoreAct) {
      var again = document.querySelector('[data-act="' + restoreAct + '"]');
      if (again) again.focus();
    }
    var panel = $('#detail');
    if (panel) fadeIn(panel, 200);
  }

  function refreshCases(alertId) {
    return Promise.all([
      api('/api/cases'),
      alertId ? api('/api/alerts/' + encodeURIComponent(alertId))
        .catch(function () { return null; }) : Promise.resolve(null)
    ]).then(function (results) {
      state.cases = results[0] || [];
      state.casesError = null;
      if (results[1] && results[1].history) {
        state.history[alertId] = results[1].history;
      }
      state.detailKey = '';
      renderAudit();
      renderDetail();
    }).catch(function (error) {
      state.casesError = (error && error.detail) || (error && error.message)
        || t('loadFailed');
      renderAudit();
    });
  }

  // A 403 from /api/alerts/{id}/action is a deliberate guardrail, not a
  // failure: it is rendered as its own provider-boundary notice in place, with
  // the server's own wording, rather than as a generic error toast.
  function showBoundary(error) {
    var host = $('#boundary');
    if (!host) { toast((error && error.detail) || t('actionFailed'), true); return; }
    host.innerHTML = '<div class="boundary-note"><b>' + esc(t('boundaryHead'))
      + '</b> ' + esc(error.detail || '') + '<br>' + esc(error.boundary || '')
      + '</div>';
    if (host.scrollIntoView) host.scrollIntoView({ block: 'nearest' });
  }

  /* ---------------------------------------------------------------- events */

  function onClick(event) {
    var node = event.target;
    if (!node || !node.closest) return;

    var act = node.closest('[data-act]');
    if (act) { event.preventDefault(); doAction(act.getAttribute('data-act')); return; }

    var open = node.closest('[data-open-alert]');
    if (open) {
      event.preventDefault();
      selectAlert(open.getAttribute('data-open-alert'));
      return;
    }

    var dot = node.closest('[data-outlet]');
    if (dot) { focusOutlet(dot.getAttribute('data-outlet')); return; }

    var item = node.closest('[data-alert]');
    if (item) { selectAlert(item.getAttribute('data-alert')); return; }

    if (node.closest('#lang-toggle')) { setLang(state.lang === 'bn' ? 'en' : 'bn'); }
  }

  function onQueueKeydown(event) {
    var keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
    if (keys.indexOf(event.key) === -1) return;
    var buttons = $('#queue').querySelectorAll('[data-alert]');
    if (!buttons.length) return;
    event.preventDefault();
    var current = -1;
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].getAttribute('data-alert') === state.selectedId) current = i;
    }
    var next = current;
    if (event.key === 'ArrowDown') next = current < 0 ? 0 : current + 1;
    if (event.key === 'ArrowUp') next = current < 0 ? 0 : current - 1;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next < 0) next = 0;
    if (next > buttons.length - 1) next = buttons.length - 1;
    selectAlert(buttons[next].getAttribute('data-alert'));
    buttons[next].focus();
  }

  function onScenarioChange(event) {
    var scenario = event.target.value;
    simulate({ scenario: scenario, demand_multiplier: state.demand },
             function () { toast(t('scenarioChanged')); });
  }

  function onDemandInput(event) {
    var value = parseFloat(event.target.value);
    if (!finite(value)) return;
    var output = document.querySelector('#wi-angle output');
    if (output) output.textContent = fRatio(value) + '×';
  }

  var demandTimer = null;
  function onDemandChange(event) {
    var value = parseFloat(event.target.value);
    if (!finite(value)) return;
    if (demandTimer) window.clearTimeout(demandTimer);
    demandTimer = window.setTimeout(function () {
      simulate({ demand_multiplier: value });
    }, 220);
  }

  function onEventToggle() {
    var node = $('#wi-event');
    var on = node && node.getAttribute('aria-pressed') === 'true';
    simulate({ demand_multiplier: on ? 1.0 : EVENT_DEMAND });
  }

  function onRunClick() { simulate({ demand_multiplier: state.demand }); }

  function boot() {
    state.lang = document.documentElement.getAttribute('data-lang') === 'en'
      ? 'en' : 'bn';
    state.actor = '';
    applyI18n();

    document.addEventListener('click', onClick);

    var queue = $('#queue');
    if (queue) queue.addEventListener('keydown', onQueueKeydown);

    var scenario = $('#scenario');
    if (scenario) scenario.addEventListener('change', onScenarioChange);

    var whatif = $('#whatif');
    if (whatif) {
      whatif.addEventListener('input', function (event) {
        if (event.target && event.target.id === 'wi-demand') onDemandInput(event);
      });
      whatif.addEventListener('change', function (event) {
        if (event.target && event.target.id === 'wi-demand') onDemandChange(event);
      });
      whatif.addEventListener('click', function (event) {
        var node = event.target;
        if (!node || !node.closest) return;
        if (node.closest('#wi-event')) { event.preventDefault(); onEventToggle(); }
        else if (node.closest('#wi-run')) { event.preventDefault(); onRunClick(); }
      });
    }

    refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
