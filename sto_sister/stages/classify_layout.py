from typing import Any, Callable, Dict, List, Tuple, Optional

from ..pipeline import PipelineStage, StageOutput, PipelineState
from ..components.layout_classifier import LayoutClassifier


class ClassifyLayoutStage(PipelineStage):
    name = "classify_layout"

    def __init__(self, opts: Dict[str, Any], app_config: Dict[str, Any]):
        super().__init__(opts, app_config)
        self.classifier = LayoutClassifier(**opts)

    def process(
        self, ctx: PipelineState, report: Callable[[str, float], None]
    ) -> StageOutput:
        report(self.name, 0.0)

        # Classify each screenshot
        # ctx.classifications = [
        #     self.classifier.classify(labels)
        #     for labels in ctx.labels_list
        # ]

        # # Pick main build as highest score
        # main_idx = max(range(len(ctx.classifications)), key=lambda i: ctx.classifications[i]["score"])
        # ctx.main_index = main_idx

        # ctx.classification = ctx.classifications[main_idx]


        # 1) Run the classifier over each label‐set
        raw_classifications = [
            self.classifier.classify(labels)
            for labels in ctx.labels_list
        ]

        #print(f"raw_classifications: {raw_classifications}")
        ctx.classifications = []
        for result in raw_classifications:
            # result: Dict[build_type, {'score': float, 'is_required': bool}]
            print (f"result: {result}")

            winning_classifications = []
            # 2) Pick the highest‐scoring build_type
            best_type, best_info = max(
                result.items(),
                key=lambda kv: kv[1]['score']   # now kv[1] is a dict, so we pull ['score']
            )
            winning_classifications.append({
                'build_type':  best_type,
                'score':       best_info['score'],
                'is_required': best_info['is_required'],
                #'details':     result,          # preserve the per‐type breakdown
            })

            # 3) Also include any other build_types that were marked required
            for btype, info in result.items():
                if info['is_required'] and btype != best_type:
                    winning_classifications.append({
                        'build_type':  btype,
                        'score':       info['score'],
                        'is_required': True,
                        #'details':     result,
                    })

            ctx.classifications.append(winning_classifications)

        # 4) Choose main_index as the highest‐scoring non‐required “winner” among runs
        #    ctx.classifications is List[List[Dict]], and winners[0] is the best build for that run.
        candidates = [
            (i, winners[0])
            for i, winners in enumerate(ctx.classifications)
            if not winners[0]['is_required']
        ]
        if candidates:
            # pick the run index whose top winner has the highest score
            ctx.main_index = max(candidates, key=lambda x: x[1]['score'])[0]
        else:
            # fallback if every run’s winner is required: pick the highest‐scoring winner anyway
            all_winners = [(i, winners[0]) for i, winners in enumerate(ctx.classifications)]
            ctx.main_index = max(all_winners, key=lambda x: x[1]['score'])[0]

        # # 4) Choose main_index as the highest‐scoring non‐required entry
        # non_required = [
        #     (i, entry)
        #     for i, entry in enumerate(ctx.classifications)
        #     if not entry['is_required']
        # ]
        # if non_required:
        #     ctx.main_index = max(non_required, key=lambda x: x[1]['score'])[0]
        # else:
        #     # fallback if everything is required (shouldn’t happen per your rules)
        #     ctx.main_index = max(
        #         range(len(ctx.classifications)),
        #         key=lambda i: ctx.classifications[i]['score']
        #     )

        # 5) Stash your main build
        ctx.classification = ctx.classifications[ctx.main_index][0]

        print (f"ctx.classifications: {ctx.classifications}")
        # Attach icon_set for each classification
        bt = ctx.classification["build_type"]
        for run_winners in ctx.classifications:
            for c in run_winners:
                if bt in ("PC Ship Build"):
                    c["icon_set"] = "ship"
                    c["platform"] = "pc"
                elif bt in ("Console Ship Build"):
                    c["icon_set"] = "ship"
                    c["platform"] = "console"
                elif bt in ("PC Ground Build"):
                    c["icon_set"] = "pc_ground"
                    c["platform"] = "pc"
                elif bt in ("Console Ground Build"):
                    c["icon_set"] = "console_ground"
                    c["platform"] = "console"

        # if (
        #     ctx.classification["build_type"] == "PC Ship Build"
        #     or ctx.classification["build_type"] == "Console Ship Build"
        # ):
        #     ctx.classification["icon_set"] = "ship"

        # elif ctx.classification["build_type"] == "PC Ground Build":
        #     ctx.classification["icon_set"] = "pc_ground"

        # elif ctx.classification["build_type"] == "Console Ground Build":
        #     ctx.classification["icon_set"] = "console_ground"

        report(self.name, 1.0)
        return StageOutput(ctx, ctx.classifications)
