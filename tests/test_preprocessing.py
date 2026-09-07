from app.ml.preprocessing import FeatureStandardizer
from app.ml.training_data import RankerDataset, RankerExample


def test_standardizer_fits_on_train_rows_and_handles_constant_features() -> None:
    dataset = RankerDataset(
        feature_names=("large", "constant"),
        examples=(
            RankerExample("u-1", "t-1", None, (("large", 10.0), ("constant", 2.0)), 1),
            RankerExample("u-1", "t-2", None, (("large", 20.0), ("constant", 2.0)), 0),
        ),
    )

    scaler = FeatureStandardizer.fit(dataset)
    transformed = scaler.transform_dataset(dataset)

    assert transformed[0][0] == -1.0
    assert transformed[1][0] == 1.0
    assert transformed[0][1] == 0.0
    assert transformed[1][1] == 0.0
